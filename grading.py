# -*- coding: utf-8 -*-
"""
grading.py — 调色渲染引擎
把一张图片按「风格配方」+「可调参数」渲染成成品。

输入: numpy float 数组, 形状 (H, W, 3), 值域 [0, 1] (RGB 顺序)
输出: 同形状 float [0, 1] 数组

依赖: numpy (可选 opencv / Pillow 由 serve.py 负责解码)
所有曲线使用 numpy 向量化运算, 速度足够处理普通照片。
"""

import numpy as np
try:
    import sys
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass



# ----------------------------------------------------------------------------
# 基础工具: 把滤镜拆成可复用的「算子」
# ----------------------------------------------------------------------------

def exposure(img, ev=0.0):
    """曝光: ev 每差 1 级亮度翻倍/减半"""
    if ev == 0:
        return img
    return np.clip(img * (2.0 ** ev), 0.0, 1.0)


def contrast(img, amount=1.0, pivot=0.5):
    """对比度: amount=1 不变, >1 增加, <1 降低"""
    if amount == 1.0:
        return img
    return np.clip((img - pivot) * amount + pivot, 0.0, 1.0)


def saturation(img, factor=1.0):
    """饱和度: factor=1 不变, 0 为黑白, >1 增强"""
    if factor == 1.0:
        return img
    gray = img.mean(axis=2, keepdims=True)
    return np.clip(gray + (img - gray) * factor, 0.0, 1.0)


def temperature(img, value=0.0):
    """色温: >0 偏暖(加红减蓝), <0 偏冷(加蓝减红). value 合理范围 -1..1"""
    if value == 0.0:
        return img
    r, g, b = img[..., 0], img[..., 1], img[..., 2]
    if value > 0:
        r = r * (1 + 0.25 * value)
        b = b * (1 - 0.25 * value)
    else:
        r = r * (1 + 0.25 * value)      # value<0 => 减红
        b = b * (1 - 0.25 * value)      # value<0 => 加蓝
    return np.clip(np.stack([r, g, b], axis=-1), 0.0, 1.0)


def tint(img, value=0.0):
    """色调(洋红/绿): >0 偏洋红, <0 偏绿"""
    if value == 0.0:
        return img
    r, g, b = img[..., 0], img[..., 1], img[..., 2]
    if value > 0:  # 洋红: 加红加蓝减绿
        g = g * (1 - 0.18 * value)
    else:          # 绿
        g = g * (1 - 0.18 * value)
    return np.clip(np.stack([r, g, b], axis=-1), 0.0, 1.0)


def _tonal_mask(img, low, high):
    """返回一个 [0,1] 权重图, 标出处于 [low, high] 亮度区间的像素(用于分区域着色)"""
    lum = img.mean(axis=2)
    mid = (lum - low) / (high - low + 1e-8)
    return np.clip(mid, 0.0, 1.0)


def color_balance(img, shadows, midtones, highlights):
    """色彩平衡: 三个通道分别按 阴影/中间调/高光 偏移. 每项为 (r,g,b) 增减量"""
    out = img.copy()
    sh = _tonal_mask(img, 0.0, 0.35)
    mid = _tonal_mask(img, 0.2, 0.8)
    hi = _tonal_mask(img, 0.6, 1.0)
    for layer, mask in zip((shadows, midtones, highlights), (sh, mid, hi)):
        if layer is None:
            continue
        for c in range(3):
            out[..., c] += layer[c] * mask
    return np.clip(out, 0.0, 1.0)


def split_toning(img, shadow_rgb=None, highlight_rgb=None, balance=0.0):
    """分离色调: 给阴影/高光分别染上指定颜色, balance 控制整体偏向"""
    out = img.copy()
    lum = img.mean(axis=2)
    if shadow_rgb is not None:
        w = 1.0 - np.clip(lum / 0.5, 0.0, 1.0)  # 阴影权重
        mix_rescale = min(0.35, max(0, 0.35 * (1 + balance)))
        for c in range(3):
            out[..., c] = out[..., c] * (1 - mix_rescale * w) + shadow_rgb[c] * mix_rescale * w
    if highlight_rgb is not None:
        w = np.clip((lum - 0.5) / 0.5, 0.0, 1.0)  # 高光权重
        mix_rescale = min(0.35, max(0, 0.35 * (1 - balance)))
        for c in range(3):
            out[..., c] = out[..., c] * (1 - mix_rescale * w) + highlight_rgb[c] * mix_rescale * w
    return np.clip(out, 0.0, 1.0)


def lift_black(img, value=0.0):
    """提黑(褪黑/哑光): 把黑场上抬, 产生胶片式发灰的暗部. value 0..0.5"""
    if value == 0.0:
        return img
    return np.clip(img + value * (1.0 - img), 0.0, 1.0)


def gamma(img, value=1.0):
    """gamma: >1 提亮中灰, <1 压暗 (近似, 用于清晰度/光影塑造)"""
    if value == 1.0:
        return img
    return np.clip(np.power(img, value), 0.0, 1.0)


def tone_curve(img, points):
    """
    通用分段曲线.
    points: [(x0,y0),(x1,y1),...] x/y 均在 [0,1] 内, 单调递增.
    用分段线性插值, 对 RGB 三个通道统一作用(也可只应用于亮度).
    """
    xs = np.array([p[0] for p in points], dtype=np.float64)
    ys = np.array([p[1] for p in points], dtype=np.float64)
    flat = img.reshape(-1, 3)
    # 对每个通道做插值
    flat = np.interp(flat, xs, ys).reshape(img.shape)
    return np.clip(flat, 0.0, 1.0)


def add_grain(img, amount=0.02):
    """胶片颗粒: 叠加高斯噪声"""
    if amount == 0:
        return img
    noise = np.random.normal(0, amount, img.shape).astype(np.float32)
    return np.clip(img + noise, 0.0, 1.0)


def _gaussian_blur(img, radius):
    """高斯模糊. 用 cv2(快); 无 cv2 时用 numpy 快速近似(均值滤波, 向量化)."""
    if radius <= 0:
        return img.copy()
    radius = int(radius)
    try:
        import cv2
        src = img.astype(np.float32)
        ksize = radius * 2 + 1
        return cv2.GaussianBlur(src, (ksize, ksize), 0).astype(np.float64)
    except Exception:  # noqa: E722  # 无 cv2: 用 numpy 快速盒式模糊(累积和, O(n))
        k = radius * 2 + 1
        # 三个通道一起, 用 cumsum 做滑动窗口均值(向量化, 快)
        padw = [(radius, radius), (radius, radius), (0, 0)]
        padded = np.pad(img, padw, mode="edge")
        for axis in (0, 1):
            csum = np.cumsum(padded, axis=axis)
            start = np.take(csum, np.arange(0, padded.shape[axis] - k), axis=axis)
            end = np.take(csum, np.arange(k, padded.shape[axis]), axis=axis)
            padded = (end - start) / k
        return padded


def clarity(img, amount=0.0, radius=15):
    """清晰度(局部对比度/去朦胧): 用低频估计作差增强细节. 无 scipy 依赖."""
    if amount == 0.0:
        return img
    blurred = _gaussian_blur(img, radius)
    detail = img - blurred
    return np.clip(img + detail * amount, 0.0, 1.0)


def sharpen(img, amount=0.4, radius=3):
    """锐化: 增强高频细节. 对人像/细节图友好, 让画面更清晰锐利."""
    if amount == 0.0:
        return img
    blurred = _gaussian_blur(img, radius)
    detail = img - blurred
    return np.clip(img + detail * amount, 0.0, 1.0)


def dehaze(img, amount=0.35):
    """去朦胧: 抬对比 + 轻微去灰, 让发灰/蒙了层的图变通透清晰."""
    if amount == 0.0:
        return img
    img = contrast(img, 1.0 + 0.18 * amount)
    img = clarity(img, amount * 0.6)
    return np.clip(img, 0.0, 1.0)


def vignette(img, strength=0.0):
    """暗角: strength 0..1, 边缘压暗, 聚焦中心"""
    if strength == 0.0:
        return img
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = w / 2, h / 2
    d = np.sqrt(((xx - cx) / cx) ** 2 + ((yy - cy) / cy) ** 2)
    mask = np.clip(1.0 - strength * np.clip(d - 0.4, 0.0, 1.4) / 1.4, 0.0, 1.0)
    return np.clip(img * mask[..., None], 0.0, 1.0)


# ----------------------------------------------------------------------------
# 风格库: 每个风格是一个「算子管道」, 也可被 serve.py 接收 param 叠加微调
# ----------------------------------------------------------------------------

def _blackwhite(img, warm=0.0, contrast_amt=1.05):
    gl = img.mean(axis=2, keepdims=True).repeat(3, axis=2)
    gl = contrast(gl, contrast_amt)
    if warm:
        r, g, b = gl[..., 0], gl[..., 1], gl[..., 2]
        r = np.clip(r * (1 + 0.10 * warm), 0, 1)
        b = np.clip(b * (1 - 0.10 * warm), 0, 1)
        gl = np.stack([r, g, b], axis=-1)
    return np.clip(gl, 0.0, 1.0)


def style_japan(img):
    """日系/清新: 亮度偏高、低对比、发灰暗部、青蓝高光、轻微降饱和"""
    img = exposure(img, 0.10)
    img = contrast(img, 0.88)
    img = saturation(img, 0.88)
    img = lift_black(img, 0.10)
    img = split_toning(img, shadow_rgb=(0.20, 0.24, 0.32), highlight_rgb=(0.30, 0.42, 0.48), balance=0.1)
    img = vignette(img, 0.10)
    return np.clip(img, 0.0, 1.0)


def style_japan2(img):
    """日系青蓝 (滨田英明味): 更通透的青调"""
    img = exposure(img, 0.14)
    img = contrast(img, 0.80)
    img = saturation(img, 0.80)
    img = lift_black(img, 0.08)
    img = split_toning(img, shadow_rgb=(0.30, 0.40, 0.52), highlight_rgb=(0.40, 0.55, 0.62), balance=0.12)
    img = vignette(img, 0.08)
    return np.clip(img, 0.0, 1.0)


def style_film(img):
    """胶片: 暖色、褪黑、颗粒、曲线柔化"""
    img = contrast(img, 0.95)
    img = temperature(img, 0.30)
    img = saturation(img, 0.90)
    img = lift_black(img, 0.12)
    img = split_toning(img, highlight_rgb=(0.55, 0.42, 0.28), balance=0.1)
    img = tone_curve(img, [(0, 0.02), (0.25, 0.30), (0.5, 0.55), (0.78, 0.82), (1, 1)])
    img = add_grain(img, 0.025)
    return np.clip(img, 0.0, 1.0)


def style_coolwhite(img):
    """冷白皮/通透: 提亮、轻微降饱和、冷调、肤色通透干净"""
    img = exposure(img, 0.12)
    img = contrast(img, 1.04)
    img = saturation(img, 0.88)
    img = temperature(img, -0.16)
    img = split_toning(img, highlight_rgb=(0.44, 0.50, 0.57), balance=0.06)
    img = clarity(img, 0.18)      # 增加清晰度, 避免发灰朦胧
    img = sharpen(img, 0.15)      # 轻微锐化, 面部细节更清晰
    return np.clip(img, 0.0, 1.0)


def style_hongkong(img):
    """复古港风: 高对比、浓烈红色/暖调、青色阴影、胶片感"""
    img = contrast(img, 1.22)
    img = temperature(img, 0.42)
    img = saturation(img, 1.06)
    img = split_toning(img, shadow_rgb=(0.25, 0.30, 0.40), highlight_rgb=(0.55, 0.36, 0.20), balance=0.12)
    img = lift_black(img, 0.05)
    img = add_grain(img, 0.02)
    return np.clip(img, 0.0, 1.0)


def style_tealorange(img):
    """电影感 青橙: 冷暖强对比, 高对比, 是典型的大片质感"""
    img = contrast(img, 1.18)
    img = saturation(img, 1.05)
    img = split_toning(img, shadow_rgb=(0.16, 0.32, 0.40), highlight_rgb=(0.55, 0.40, 0.22), balance=0.15)
    img = vignette(img, 0.18)
    img = tone_curve(img, [(0, 0.02), (0.35, 0.38), (0.65, 0.68), (1, 1)])
    return np.clip(img, 0.0, 1.0)


def style_vintage(img):
    """复古/老照片: 褪色、暖黄、发灰暗部"""
    img = contrast(img, 0.92)
    img = temperature(img, 0.35)
    img = saturation(img, 0.78)
    img = lift_black(img, 0.16)
    img = split_toning(img, highlight_rgb=(0.60, 0.50, 0.32), balance=0.1)
    return np.clip(img, 0.0, 1.0)


def style_warm(img):
    """暖调氛围: 暖色、柔化、云朵般的日系暖"""
    img = temperature(img, 0.40)
    img = contrast(img, 0.92)
    img = saturation(img, 0.92)
    img = lift_black(img, 0.06)
    img = vignette(img, 0.10)
    return np.clip(img, 0.0, 1.0)


def style_blackwhite(img):
    """黑白 (暖调)"""
    return _blackwhite(img, warm=0.15, contrast_amt=1.05)


def style_moon(img):
    """暗调/夜晚: 压暗、冷色、暗角、青蓝"""
    img = exposure(img, -0.12)
    img = contrast(img, 1.15)
    img = temperature(img, -0.2)
    img = saturation(img, 0.85)
    img = split_toning(img, shadow_rgb=(0.20, 0.30, 0.42), highlight_rgb=(0.35, 0.45, 0.55), balance=0.1)
    img = vignette(img, 0.25)
    return np.clip(img, 0.0, 1.0)


def style_fresh(img):
    """清新亮透: 亮、净、微降饱和, 适合阴天/逆光"""
    img = exposure(img, 0.22)
    img = contrast(img, 0.85)
    img = saturation(img, 0.82)
    img = lift_black(img, 0.06)
    img = temperature(img, -0.08)
    img = split_toning(img, highlight_rgb=(0.45, 0.55, 0.62), balance=0.08)
    return np.clip(img, 0.0, 1.0)


# 风格注册表: key -> (显示名, 处理函数, 描述)
STYLES = {
    "original": ("原图", None, "不做任何处理"),
    "japan": ("日系清新", style_japan, "亮度高、低对比、青蓝高光、发灰暗部"),
    "japan2": ("日系青蓝", style_japan2, "滨田英明味，更通透的青调"),
    "film": ("胶片", style_film, "暖色、褪黑、颗粒、曲线柔化"),
    "coolwhite": ("冷白皮", style_coolwhite, "提亮、轻微降饱和、冷调、肤色通透"),
    "hongkong": ("复古港风", style_hongkong, "高对比、浓烈红/暖调、青阴影"),
    "tealorange": ("电影青橙", style_tealorange, "青橙冷暖强对比，大片质感"),
    "vintage": ("复古", style_vintage, "褪色、暖黄、发灰暗部"),
    "warm": ("暖调氛围", style_warm, "暖色柔化、日系暖调"),
    "blackwhite": ("黑白", style_blackwhite, "黑白暖调"),
    "moon": ("夜晚暗调", style_moon, "压暗冷色、暗角"),
    "fresh": ("清新亮透", style_fresh, "亮度净透、适合阴天逆光"),
}


def apply_style(img, style_key, params=None):
    """
    主入口:
      img       : float [0,1] RGB 数组, (H,W,3)
      style_key : STYLES 的 key
      params    : dict, 可选微调项, 在风格后叠加:
                  exposure, contrast, saturation, temperature, tint, gamma
    """
    img = np.clip(img, 0.0, 1.0)
    entry = STYLES.get(style_key)
    if entry and entry[1]:
        img = entry[1](img)
    if params:
        if "exposure" in params:
            img = exposure(img, params["exposure"])
        if "gamma" in params:
            img = gamma(img, params["gamma"])
        if "contrast" in params:
            img = contrast(img, params["contrast"])
        if "saturation" in params:
            img = saturation(img, params["saturation"])
        if "temperature" in params:
            img = temperature(img, params["temperature"])
        if "tint" in params:
            img = tint(img, params["tint"])
        if "clarity" in params:
            img = clarity(img, params["clarity"])
        if "sharpen" in params:
            img = sharpen(img, params["sharpen"])
        if "dehaze" in params:
            img = dehaze(img, params["dehaze"])
    return np.clip(img, 0.0, 1.0)


# ----------------------------------------------------------------------------
# 智能自动修图: 分析图片 -> 推荐风格 + 参数
# ----------------------------------------------------------------------------

def _img_features(img):
    """提取图片的统计特征, 用于自动判断风格"""
    lum = img.mean(axis=2)
    mean_lum = float(lum.mean())
    std_lum = float(lum.std())
    # 直方图: 暗部/中间/亮部 占比
    shadow_ratio = float((lum < 0.3).mean())
    highlight_ratio = float((lum > 0.75).mean())
    mid_ratio = float(((lum >= 0.3) & (lum <= 0.75)).mean())
    # 冷暖: 红通道与蓝通道均值差
    r_mean = float(img[..., 0].mean())
    b_mean = float(img[..., 2].mean())
    warm = r_mean - b_mean  # >0 偏暖, <0 偏冷
    # 饱和度: RGB 通道差
    mx = img.max(axis=2)
    mn = img.min(axis=2)
    sat = float((mx - mn).mean())
    # 肤色检测: 用逐像素 HSV 色相+饱和度+亮度判断, 比全局阈值可靠
    r, g, b = img[..., 0], img[..., 1], img[..., 2]
    mx2 = np.maximum(np.maximum(r, g), b)
    mn2 = np.minimum(np.minimum(r, g), b)
    delta = mx2 - mn2 + 1e-8
    # 色相(H) 0-360, 用 np.select 向量化(比布尔索引快很多)
    cond = [mx2 == r, (mx2 == g) & (mx2 != r), (mx2 == b) & (mx2 != r) & (mx2 != g)]
    choice = [
        (60 * ((g - b) / delta) % 360),
        (60 * ((b - r) / delta) + 120),
        (60 * ((r - g) / delta) + 240),
    ]
    hue = np.select(cond, choice, default=0.0)
    # 逐像素饱和度 S = delta / max  (HSV 的 S)
    perc_sat = delta / (mx2 + 1e-8)
    # 肤色: 色相 0~45 红橙区 + 中等亮度 + 逐像素饱和度不算极低
    skin_mask = ((hue >= 0) & (hue <= 45)) & (lum > 0.25) & (lum < 0.92) & (perc_sat > 0.12)
    skin = float(skin_mask.mean())
    return {
        "mean_lum": mean_lum, "std_lum": std_lum,
        "shadow_ratio": shadow_ratio, "highlight_ratio": highlight_ratio, "mid_ratio": mid_ratio,
        "warm": warm, "sat": sat, "skin": skin,
    }


def auto_grade(img):
    """
    根据图片特征自动选择最合适的风格与微调参数(清晰优先)。
    返回 dict: {style, name, params, reason, features}
    """
    f = _img_features(img)
    reason = []
    style = "fresh"
    params = {}

    lum = f["mean_lum"]
    std = f["std_lum"]
    sat = f["sat"]
    warm = f["warm"]
    skin = f["skin"]
    shadow = f["shadow_ratio"]
    mid = f["mid_ratio"]
    highlight = f["highlight_ratio"]

    # ---- 夜景评分: 真夜景通常 暗 + 冷 + 高光点少 + 中间调也偏少(要么很暗要么有灯) ----
    #   这里用 "暗且高光极少" 作为主条件, 避免把偏暗的正常照片误判成夜景
    night_score = (0.5 * (1 - lum)) + (0.3 * (-min(warm, 0))) + (0.2 * (mid < 0.4))
    is_night = (lum < 0.30) and (highlight < 0.10) and (shadow > 0.55) and (mid < 0.42)

    # ---- 人像判定: 严格肤色+非暗调 ----
    is_portrait = (skin > 0.15) and (lum >= 0.32) and (shadow < 0.6)

    if is_night:
        # 夜景: 用户要"不糊", 所以提亮+清晰让暗部细节可见, 而非压暗的朦胧
        reason.append("检测到夜景/偏暗 → 提亮并清晰化，让细节可见")
        params["exposure"] = 0.12   # fresh 本身含 exposure 0.22, 二者叠加不过曝
        params["clarity"] = 0.32
        params["sharpen"] = 0.15
        params["temperature"] = -0.05
        if sat < 0.2:
            params["contrast"] = 1.08
        style = "fresh"
    elif is_portrait:
        style = "coolwhite"
        reason.append("检测到真人肤色(人像) → 用冷白皮通透")
        if sat > 0.45:
            params["saturation"] = 0.9
        if warm > 0.12:
            params["temperature"] = -0.08  # 去除偏黄
        params["clarity"] = 0.25
        params["sharpen"] = 0.18
        if lum < 0.5:
            params["exposure"] = 0.06
        if std < 0.18:
            params["contrast"] = 1.05
    elif lum < 0.40:
        # 偏暗但有内容: 优先提亮+去朦胧, 不用压暗的 moon
        reason.append("偏暗但仍有细节 → 提亮并清晰化")
        params["exposure"] = 0.14
        params["clarity"] = 0.22
        params["sharpen"] = 0.12
        style = "fresh" if sat < 0.35 else "warm"
        if sat >= 0.42:
            style = "warm"
        # 提亮后若偏冷偏灰用日系, 否则清新
        if sat < 0.28 and lum < 0.5:
            style = "japan"
            params["contrast"] = 0.96
    elif sat >= 0.42 and skin <= 0.25:
        if warm > 0.05:
            style = "warm"
            reason.append("色彩鲜艳且偏暖 → 暖调氛围提质感")
        else:
            style = "tealorange"
            reason.append("色彩鲜艳(风景/食物) → 电影青橙大片感")
        params["contrast"] = 1.08
        params["clarity"] = 0.2
    elif sat < 0.28:
        if lum > 0.55:
            style = "fresh"
            reason.append("低饱和且亮 → 清新亮透")
        else:
            style = "japan"
            reason.append("低饱和发灰 → 日系清新")
        params["contrast"] = 0.96
        params["clarity"] = 0.22
        params["sharpen"] = 0.15
    else:
        # 默认: 综合判断
        if std > 0.24:
            style = "tealorange"
            reason.append("对比强 → 电影青橙")
        elif warm > 0.10:
            style = "warm"
            reason.append("整体偏暖 → 暖调氛围")
        elif lum > 0.6 and sat < 0.4:
            style = "japan"
            reason.append("亮且柔 → 日系")
        else:
            style = "fresh"
            reason.append("适中 → 清新亮透")
        params["contrast"] = 1.0
        params["clarity"] = 0.16

    # 统一保证端到端清晰: 若最后仍未加任何清晰度, 补一个轻微锐化
    if "clarity" not in params and "sharpen" not in params:
        params["sharpen"] = 0.12

    style_name = STYLES[style][0]
    # 清理无用参数
    params = {k: v for k, v in params.items() if v not in (0, 0.0, 1, 1.0)}
    return {
        "style": style,
        "name": style_name,
        "params": params,
        "reason": "；".join(reason) if reason else "自动判断",
        "features": {k: round(v, 3) for k, v in f.items()},
    }


if __name__ == "__main__":
    # 冒烟测试: 随便造一张渐变图, 跑所有风格, 确保不报错
    import sys
    h, w = 400, 600
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    img = np.stack([xx / w, yy / h, ((xx / w) + (yy / h)) / 2], axis=-1)
    img = np.clip(img, 0, 1).astype(np.float64)
    for key in STYLES:
        out = apply_style(img, key)
        assert out.shape == img.shape
        assert out.dtype == img.dtype
        assert np.isfinite(out).all()
        print("OK  %-12s -> %s" % (key, STYLES[key][0]))
    # 自动分析
    rec = auto_grade(img)
    print("auto_grade -> style=%s reason=%s" % (rec["style"], rec["reason"]))
    print("ALL_STYLES_PASSED")

