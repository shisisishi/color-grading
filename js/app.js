/* js/app.js — 前端逻辑：tab 切换、风格选择、上传、渲染、下载、服务器状态 */
(function () {
  "use strict";

  // ---------- 全局状态 ----------
  const state = {
    originalBase64: null,   // 原始上传图片的 base64
    originalBlob: null,     // 原始 Blob
    renderedBase64: null,   // 渲染后 base64 (png)
    currentStyle: "original",
    styles: [],
    samples: [],            // 示例图库
  };

  const API = {
    check: "/check",
    styles: "/api/styles",
    process: "/api/process",
    autograde: "/api/autograde",
    download: "/api/download",
    samples: "/api/samples",
  };

  // ---------- tab 切换 ----------
  const tabs = document.querySelectorAll(".tab");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const name = tab.dataset.tab;
      tabs.forEach((t) => t.classList.toggle("active", t === tab));
      document.querySelectorAll(".panel").forEach((p) => {
        p.classList.toggle("active", p.id === "tab-" + name);
      });
      if (name === "workbench" && !state.styles.length) loadStyles();
    });
  });

  // ---------- 服务器状态 ----------
  async function checkServer() {
    const el = document.getElementById("serverStatus");
    try {
      const r = await fetch(API.check);
      const j = await r.json();
      if (j.ok) {
        el.textContent = "服务器在线 · " + j.styles + " 风格 · " + j.backend;
        el.className = "server-status ok";
        loadStyles();
      } else {
        throw new Error("bad");
      }
    } catch (e) {
      el.textContent = "⚠️ 服务器未连接，请运行 python serve.py";
      el.className = "server-status err";
    }
  }

  // ---------- 加载风格列表 ----------
  async function loadStyles() {
    try {
      const r = await fetch(API.styles);
      const j = await r.json();
      state.styles = j.styles || [];
      renderStyleChips();
      renderRecipes();
    } catch (e) {
      document.getElementById("styleGrid").innerHTML = "<p style='color:#ff7a7a'>风格列表加载失败</p>";
    }
  }

  function renderStyleChips() {
    const grid = document.getElementById("styleGrid");
    grid.innerHTML = "";
    state.styles.forEach((s) => {
      const btn = document.createElement("button");
      btn.className = "style-chip" + (s.key === state.currentStyle ? " active" : "");
      btn.dataset.key = s.key;
      const n = document.createElement("span");
      n.className = "n";
      n.textContent = s.name;
      const d = document.createElement("span");
      d.className = "desc";
      d.textContent = s.key === "original" ? "不做处理" : s.desc;
      btn.appendChild(n);
      btn.appendChild(d);
      btn.addEventListener("click", () => {
        state.currentStyle = s.key;
        renderStyleChips();
        if (state.originalBase64) autoRender();
      });
      grid.appendChild(btn);
    });
  }

  function renderRecipes() {
    const list = document.getElementById("recipeList");
    list.innerHTML = "";
    const tagMap = { original: [], japan: ["c1","低对比","青高光"], japan2: ["c1","通透","青蓝"], film: ["c2","暖","褪黑"], coolwhite: ["c1","通透","冷调"], hongkong: ["c2","高对比","复古"], tealorange: ["c3","青橙","电影"], vintage: ["c2","褪色","暖黄"], warm: ["c2","暖调"], blackwhite: ["c1","黑白"], moon: ["c3","暗调","冷"], fresh: ["c1","亮透"] };
    state.styles.forEach((s) => {
      if (s.key === "original") return;
      const card = document.createElement("div");
      card.className = "recipe";
      const h = document.createElement("h3");
      h.textContent = s.name;
      const rd = document.createElement("div");
      rd.className = "rd";
      rd.textContent = s.desc;
      const tags = document.createElement("div");
      tags.className = "rtags";
      (tagMap[s.key] || []).forEach((t) => {
        if (t.length > 3) {
          const tg = document.createElement("span");
          tg.className = "rtag c1";
          tg.textContent = t;
          tags.appendChild(tg);
        } else {
          const tg = document.createElement("span");
          tg.className = "rtag " + t;
          tg.textContent = t;
          tags.appendChild(tg);
        }
      });
      const tryBtn = document.createElement("div");
      tryBtn.className = "try";
      tryBtn.textContent = "→ 去工作台用这个风格";
      tryBtn.addEventListener("click", () => {
        state.currentStyle = s.key;
        document.querySelector('.tab[data-tab="workbench"]').click();
        renderStyleChips();
        if (state.originalBase64) autoRender();
      });
      card.appendChild(h);
      card.appendChild(rd);
      card.appendChild(tags);
      card.appendChild(tryBtn);
      list.appendChild(card);
    });
  }

  // ---------- 上传处理 ----------
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("fileInput");
  const browseBtn = document.getElementById("browseBtn");

  browseBtn.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", (e) => {
    if (e.target.files && e.target.files[0]) handleFile(e.target.files[0]);
  });

  ["dragenter", "dragover"].forEach((ev) =>
    dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.add("over"); })
  );
  ["dragleave", "drop"].forEach((ev) =>
    dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.remove("over"); })
  );
  dropzone.addEventListener("drop", (e) => {
    if (e.dataTransfer.files && e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
  });

  function handleFile(file) {
    if (!file.type.startsWith("image/")) {
      document.getElementById("renderStatus").textContent = "请上传图片文件";
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      state.originalBase64 = reader.result.split(",")[1];
      state.originalBlob = file;
      state.renderedBase64 = null;
      document.getElementById("originPreview").hidden = false;
      document.getElementById("originImg").src = URL.createObjectURL(file);
      document.getElementById("renderBtn").disabled = false;
      document.getElementById("autoBtn").disabled = false;
      document.getElementById("downloadBtn").disabled = true;
      document.getElementById("resultArea").hidden = true;
      setStatus("图片已载入，点「🤖 智能自动修图」或选风格后点渲染", "ok", false);
      autoRender();
    };
    reader.readAsDataURL(file);
  }

  // ---------- 示例图库 ----------
  async function loadSamples() {
    try {
      const r = await fetch(API.samples);
      const j = await r.json();
      state.samples = j.samples || [];
      renderSampleGrid();
    } catch (e) {
      document.getElementById("sampleGrid").innerHTML = "<p style='color:#ff7a7a'>示例加载失败</p>";
    }
  }

  function renderSampleGrid() {
    const grid = document.getElementById("sampleGrid");
    if (!grid) return;
    grid.innerHTML = "";
    state.samples.forEach((s) => {
      const cell = document.createElement("div");
      cell.className = "sample-thumb" + (s.name === state.activeSample ? " active" : "");
      cell.dataset.name = s.name;
      const img = document.createElement("img");
      img.src = "/samples/" + s.name + ".jpg";
      img.alt = s.label;
      img.loading = "lazy";
      const t = document.createElement("span");
      t.className = "t";
      t.textContent = s.label;
      cell.appendChild(img);
      cell.appendChild(t);
      cell.addEventListener("click", () => loadSample(s));
      grid.appendChild(cell);
    });
    state.activeSample = state.activeSample || null;
  }

  function loadSample(s) {
    fetch("/samples/" + s.name + ".jpg")
      .then((r) => {
        if (!r.ok) throw new Error("加载失败");
        return r.blob();
      })
      .then((blob) => {
        state.activeSample = s.name;
        // 更新缩略图高亮
        document.querySelectorAll(".sample-thumb").forEach((el) => el.classList.toggle("active", el.dataset.name === s.name));
        // 把 blob 转 base64 存入 state, 复用现有渲染管线
        const fr = new FileReader();
        fr.onload = () => {
          state.originalBase64 = fr.result.split(",")[1];
          state.originalBlob = blob;
          state.renderedBase64 = null;
          document.getElementById("originPreview").hidden = false;
          document.getElementById("originImg").src = "/samples/" + s.name + ".jpg";
          document.getElementById("renderBtn").disabled = false;
          document.getElementById("autoBtn").disabled = false;
          document.getElementById("downloadBtn").disabled = true;
          document.getElementById("resultArea").hidden = true;
          setStatus("已载入示例「" + s.label + "」，点「🤖 智能自动修图」", "ok", false);
          autoRender();
        };
        fr.readAsDataURL(blob);
      })
      .catch((e) => setStatus("载入失败: " + e.message, "err"));
  }

  // ---------- 参数 ----------
  const paramDefs = [
    ["exposure", "v-exposure"],
    ["contrast", "v-contrast"],
    ["saturation", "v-saturation"],
    ["temperature", "v-temperature"],
  ];
  paramDefs.forEach(([id, vid]) => {
    const el = document.getElementById("p-" + id);
    const v = document.getElementById(vid);
    el.addEventListener("input", () => {
      v.textContent = parseFloat(el.value).toFixed(2);
      if (state.originalBase64) maybeRenderDebounced();
    });
  });

  function collectParams() {
    const p = {};
    const val = (id) => parseFloat(document.getElementById("p-" + id).value);
    const exp = val("exposure");
    const con = val("contrast");
    const sat = val("saturation");
    const tem = val("temperature");
    if (exp !== 0) p.exposure = exp;
    if (con !== 1) p.contrast = con;
    if (sat !== 1) p.saturation = sat;
    if (tem !== 0) p.temperature = tem;
    return p;
  }

  let renderTimer = null;
  function maybeRenderDebounced() {
    clearTimeout(renderTimer);
    renderTimer = setTimeout(() => autoRender(), 220);
  }

  // ---------- 渲染 ----------
  const renderBtn = document.getElementById("renderBtn");
  const downloadBtn = document.getElementById("downloadBtn");
  const autoBtn = document.getElementById("autoBtn");
  renderBtn.addEventListener("click", autoRender);

  // 把推荐参数写回滑杆+显示值
  function setParamValue(id, val) {
    const el = document.getElementById("p-" + id);
    if (!el) return;
    el.value = val;
    const v = document.getElementById("v-" + id);
    if (v) v.textContent = parseFloat(val).toFixed(2);
  }

  // ---------- 智能自动修图 ----------
  autoBtn.addEventListener("click", autoGrade);

  async function autoGrade() {
    if (!state.originalBase64) return;
    autoBtn.disabled = true;
    renderBtn.disabled = true;
    setStatus("🤖 正在分析这张照片并自动修图…", "ok", false);
    try {
      const payload = { image: state.originalBase64 };
      const r = await fetch(API.autograde, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const j = await r.json();
      if (!j.ok) {
        setStatus("自动修图失败: " + (j.error || "未知"), "err");
        return;
      }
      // 回填推荐风格chip高亮
      state.currentStyle = j.style;
      renderStyleChips();
      // 回填推荐的微调参数
      const p = j.params || {};
      setParamValue("exposure", p.exposure || 0);
      setParamValue("contrast", p.contrast || 1);
      setParamValue("saturation", p.saturation || 1);
      setParamValue("temperature", p.temperature || 0);
      // 展示成品
      state.renderedBase64 = j.image;
      const src = "data:image/png;base64," + j.image;
      document.getElementById("resultArea").hidden = false;
      document.getElementById("cmpBefore").src = document.getElementById("originImg").src;
      document.getElementById("cmpAfter").src = src;
      downloadBtn.disabled = false;
      setStatus("🤖 已选「" + j.name + "」自动修图完成 ✓ | " + (j.reason || ""), "ok", false);
    } catch (e) {
      setStatus("自动修图失败: " + e.message, "err");
    } finally {
      autoBtn.disabled = false;
      renderBtn.disabled = false;
    }
  }

  async function autoRender() {
    if (!state.originalBase64) return;
    renderBtn.disabled = true;
    setStatus("正在渲染…", "ok", false);
    try {
      const payload = {
        image: state.originalBase64,
        style: state.currentStyle,
        params: collectParams(),
      };
      const r = await fetch(API.process, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const j = await r.json();
      if (!j.ok) {
        setStatus("渲染失败: " + (j.error || "未知"), "err");
        return;
      }
      state.renderedBase64 = j.image;
      const src = "data:image/png;base64," + j.image;
      document.getElementById("resultArea").hidden = false;
      document.getElementById("cmpBefore").src = document.getElementById("originImg").src;
      document.getElementById("cmpAfter").src = src;
      downloadBtn.disabled = false;
      setStatus("渲染完成 ✓ (" + j.width + "×" + j.height + ")", "ok", false);
    } catch (e) {
      setStatus("渲染失败: " + e.message, "err");
    } finally {
      renderBtn.disabled = false;
    }
  }

  function setStatus(text, cls, show = true) {
    const el = document.getElementById("renderStatus");
    el.textContent = text;
    el.className = "render-status " + cls;
    if (!show) { /* keep */ }
  }

  // ---------- 下载 ----------
  downloadBtn.addEventListener("click", async () => {
    if (!state.renderedBase64) return;
    try {
      const payload = { image: state.renderedBase64, name: "graded_" + state.currentStyle + ".png" };
      const r = await fetch(API.download, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = payload.name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      setStatus("下载失败: " + e.message, "err");
    }
  });

  // ---------- init ----------
  checkServer();
  loadSamples();
})();
