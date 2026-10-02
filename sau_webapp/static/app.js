/* social-auto-upload Web 管理台（无构建，Vue3 + Element Plus + ECharts 本地 vendor） */
const { createApp, nextTick } = Vue;

const ROUTES = [
  { key: "dashboard", label: "仪表盘", icon: "📊" },
  { key: "accounts", label: "账号管理", icon: "👤" },
  { key: "materials", label: "素材库", icon: "🎬" },
  { key: "publish", label: "发布任务", icon: "🚀" },
  { key: "tasks", label: "任务记录", icon: "📋" },
];

const TASK_TYPE_LABELS = { login: "扫码登录", check: "检查登录态", upload: "发布" };

const PLATFORM_META = {
  douyin: { icon: "🎵", color: "#1f2d3d" },
  kuaishou: { icon: "⚡", color: "#ff7d25" },
  xiaohongshu: { icon: "📕", color: "#ff2442" },
  bilibili: { icon: "📺", color: "#00aeec" },
  tencent: { icon: "💚", color: "#07c160" },
  baijiahao: { icon: "📰", color: "#2932e1" },
  alipay: { icon: "💙", color: "#1677ff" },
  weibo: { icon: "🔥", color: "#e6162d" },
  hupu: { icon: "🏀", color: "#c01e2e" },
  youtube: { icon: "▶️", color: "#ff0000" },
  tiktok: { icon: "🎧", color: "#fe2c55" },
  instagram: { icon: "📸", color: "#e1306c" },
  facebook: { icon: "📘", color: "#1877f2" },
  x: { icon: "𝕏", color: "#000000" },
};

const CHART_COLORS = ["#409eff", "#34c77b", "#ff9f40", "#7b5cff", "#ff6b81", "#00c9a7", "#f8b422", "#5f7bff", "#a78bfa", "#38d9a9"];

function fmtSize(bytes) {
  if (bytes >= 1024 * 1024 * 1024) return (bytes / 1024 / 1024 / 1024).toFixed(2) + " GB";
  if (bytes >= 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + " MB";
  if (bytes >= 1024) return (bytes / 1024).toFixed(0) + " KB";
  return bytes + " B";
}

function fmtDuration(seconds) {
  if (!seconds || seconds <= 0) return "";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

const app = createApp({
  data() {
    return {
      route: "dashboard",
      routes: ROUTES,
      meta: { platforms: [], zones: { bilibili_tid: [], tencent_category: [] }, version: "" },
      stats: null,
      accounts: [],
      materials: [],
      tasks: [],
      taskFilter: "",
      tasksTimer: null,
      checking: {},

      // 添加账号 / 扫码登录
      addDialog: { visible: false },
      loginDialog: { visible: false, task: null, timer: null },

      // 上传 cookie
      cookieDialog: { visible: false, platform: "bilibili", accountName: "", fileName: "", fileData: null, submitting: false },

      // 素材预览
      preview: { visible: false, type: "", name: "" },

      // 素材上传
      uploading: false,
      dragover: false,

      // 发布表单
      form: {
        platform: "douyin",
        contentType: "video",
        accountName: "",
        file: "",
        images: [],
        title: "",
        desc: "",
        note: "",
        tags: "",
        scheduleEnabled: false,
        scheduleTime: "",
        thumbnail: "",
        thumbnailLandscape: "",
        thumbnailPortrait: "",
        headless: true,
        extras: {
          tid: "",
          visibility: "public",
          playlist: "",
          short_title: "",
          category: "",
          is_draft: false,
          collection_name: "",
          bgm: "",
          declaration: "",
          product_link: "",
          product_title: "",
        },
      },
      submitting: false,
      verifyPrompted: {},
    };
  },

  computed: {
    currentSpec() {
      return this.meta.platforms.find((p) => p.key === this.form.platform) || null;
    },
    qrcodePlatforms() {
      return this.meta.platforms.filter((p) => p.login_mode === "qrcode");
    },
    videoMaterials() {
      return this.materials.filter((m) => m.type === "video");
    },
    imageMaterials() {
      return this.materials.filter((m) => m.type === "image");
    },
    platformAccounts() {
      return this.accounts.filter((a) => a.platform === this.form.platform);
    },
    filteredTasks() {
      if (!this.taskFilter) return this.tasks;
      return this.tasks.filter((t) => t.type === this.taskFilter);
    },
    hasRunningTasks() {
      return this.tasks.some((t) => t.status === "pending" || t.status === "running");
    },
    todayBucket() {
      if (!this.stats || !this.stats.tasks_by_day) return { success: 0, failed: 0, other: 0 };
      const list = this.stats.tasks_by_day;
      return list[list.length - 1] || { success: 0, failed: 0, other: 0 };
    },
    successRate() {
      const done = (this.stats?.tasks_success || 0) + (this.stats?.tasks_failed || 0);
      if (!done) return "—";
      return Math.round(((this.stats.tasks_success || 0) / done) * 100) + "%";
    },

    // 发布预览卡数据
    previewCover() {
      if (this.form.contentType === "note") {
        return this.form.images.length ? this.posterUrl(this.form.images[0]) : "";
      }
      return this.form.file && !this.form.file.includes("/") ? this.posterUrl(this.form.file) : "";
    },
    previewDesc() {
      if (this.form.contentType === "note") return this.form.note || this.form.desc;
      return this.form.desc;
    },
    previewTagList() {
      return this.form.tags
        .split(/[,，]/)
        .map((t) => t.trim().replace(/^#/, ""))
        .filter(Boolean)
        .slice(0, 8);
    },
  },

  methods: {
    async api(path, options = {}) {
      const opts = { ...options };
      if (opts.body && !(opts.body instanceof FormData)) {
        opts.headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
        opts.body = JSON.stringify(opts.body);
      }
      const resp = await fetch(path, opts);
      let data = {};
      try {
        data = await resp.json();
      } catch (e) {
        /* 空响应 */
      }
      if (!resp.ok) {
        throw new Error(data.detail || `请求失败 (${resp.status})`);
      }
      return data;
    },

    go(route) {
      location.hash = "#" + route;
    },

    platformName(key) {
      const spec = this.meta.platforms.find((p) => p.key === key);
      return spec ? spec.name : key;
    },

    platformIcon(key) {
      return (PLATFORM_META[key] || {}).icon || "📡";
    },

    isQrPlatform(key) {
      const spec = this.meta.platforms.find((p) => p.key === key);
      return !!spec && spec.login_mode === "qrcode";
    },

    taskTypeLabel(type) {
      return TASK_TYPE_LABELS[type] || type;
    },

    statusTagType(status) {
      if (status === "success") return "success";
      if (status === "failed") return "danger";
      if (status === "running") return "primary";
      return "info";
    },

    statusLabel(status) {
      return { pending: "排队中", running: "执行中", success: "成功", failed: "失败" }[status] || status;
    },

    fmtSize,
    fmtDuration,

    materialUrl(name) {
      return `/api/materials/${encodeURIComponent(name)}/file`;
    },

    posterUrl(name) {
      return `/api/materials/${encodeURIComponent(name)}/poster`;
    },

    // ------------------------------------------------------------------ 加载

    async loadMeta() {
      try {
        this.meta = await this.api("/api/meta");
      } catch (e) {
        ElementPlus.ElMessage.error("加载平台信息失败: " + e.message);
      }
    },

    async loadStats() {
      try {
        this.stats = await this.api("/api/stats");
        this.renderCharts();
      } catch (e) {
        /* 静默 */
      }
    },

    async loadAccounts() {
      try {
        const data = await this.api("/api/accounts");
        this.accounts = data.accounts;
      } catch (e) {
        ElementPlus.ElMessage.error("加载账号失败: " + e.message);
      }
    },

    async loadMaterials() {
      try {
        const data = await this.api("/api/materials");
        this.materials = data.materials;
      } catch (e) {
        ElementPlus.ElMessage.error("加载素材失败: " + e.message);
      }
    },

    async loadTasks() {
      try {
        const data = await this.api("/api/tasks?limit=100");
        this.tasks = data.tasks;
        this.checkVerifyPrompt();
      } catch (e) {
        /* 静默，任务页会自动重试 */
      }
    },

    // 检测到任务等待短信验证码时自动弹输入框（每个任务只提醒一次）
    checkVerifyPrompt() {
      for (const task of this.tasks) {
        if (!task.waiting_verify_code || this.verifyPrompted[task.id]) continue;
        this.verifyPrompted = { ...this.verifyPrompted, [task.id]: true };
        this.promptVerifyCode(task);
        break; // 一次只弹一个
      }
    },

    async promptVerifyCode(task) {
      let code = "";
      try {
        const result = await ElementPlus.ElMessageBox.prompt(
          `抖音发布需要短信验证码（账号 ${task.account}）。请输入手机收到的验证码：`,
          "📱 短信验证码",
          {
            confirmButtonText: "提交验证码",
            cancelButtonText: "暂不输入",
            inputPattern: /^\d{4,8}$/,
            inputErrorMessage: "验证码应为 4-8 位数字",
          }
        );
        code = result.value;
      } catch (e) {
        return; // 用户暂不输入，仍可通过任务页按钮再次提交
      }
      await this.submitVerifyCode(task.id, code);
    },

    async submitVerifyCode(taskId, code) {
      try {
        const result = await this.api(`/api/tasks/${taskId}/verify-code`, {
          method: "POST",
          body: { code },
        });
        ElementPlus.ElMessage.success(result.message || "验证码已提交");
      } catch (e) {
        ElementPlus.ElMessage.error(e.message);
      }
    },

    // ------------------------------------------------------------------ 图表

    ensureChart(key) {
      if (!window.echarts) return null;
      if (!this._charts) this._charts = {};
      if (this._charts[key]) return this._charts[key];
      const el = document.getElementById("chart-" + key);
      if (!el) return null;
      this._charts[key] = window.echarts.init(el);
      return this._charts[key];
    },

    disposeCharts() {
      if (!this._charts) return;
      Object.values(this._charts).forEach((chart) => chart.dispose());
      this._charts = {};
    },

    resizeCharts() {
      if (!this._charts) return;
      Object.values(this._charts).forEach((chart) => chart.resize());
    },

    renderCharts() {
      if (this.route !== "dashboard" || !this.stats) return;
      const trend = this.ensureChart("trend");
      if (trend) {
        const days = this.stats.tasks_by_day || [];
        trend.setOption({
          color: ["#34c77b", "#f56c6c", "#c0c4cc"],
          tooltip: { trigger: "axis" },
          legend: { data: ["成功", "失败", "进行中"], bottom: 0, itemWidth: 12, itemHeight: 8, textStyle: { fontSize: 11 } },
          grid: { left: 34, right: 14, top: 18, bottom: 34 },
          xAxis: {
            type: "category",
            data: days.map((d) => d.day.slice(5)),
            axisLine: { lineStyle: { color: "#dcdfe6" } },
            axisLabel: { color: "#909399", fontSize: 11 },
          },
          yAxis: {
            type: "value",
            minInterval: 1,
            splitLine: { lineStyle: { color: "#f0f2f5" } },
            axisLabel: { color: "#909399", fontSize: 11 },
          },
          series: [
            { name: "成功", type: "bar", stack: "total", barMaxWidth: 26, data: days.map((d) => d.success) },
            { name: "失败", type: "bar", stack: "total", barMaxWidth: 26, data: days.map((d) => d.failed) },
            { name: "进行中", type: "bar", stack: "total", barMaxWidth: 26, data: days.map((d) => d.other) },
          ],
        });
      }

      const platform = this.ensureChart("platform");
      if (platform) {
        const entries = Object.entries(this.stats.tasks_by_platform || {});
        platform.setOption(
          entries.length
            ? {
                color: CHART_COLORS,
                tooltip: { trigger: "item", formatter: "{b}: {c} 次 ({d}%)" },
                legend: { bottom: 0, itemWidth: 12, itemHeight: 8, textStyle: { fontSize: 11 } },
                series: [
                  {
                    type: "pie",
                    radius: ["42%", "68%"],
                    center: ["50%", "44%"],
                    avoidLabelOverlap: true,
                    itemStyle: { borderRadius: 6, borderColor: "#fff", borderWidth: 2 },
                    label: { show: false },
                    data: entries.map(([key, value]) => ({
                      name: this.platformName(key),
                      value,
                    })),
                  },
                ],
              }
            : {
                title: {
                  text: "暂无任务数据",
                  left: "center",
                  top: "middle",
                  textStyle: { color: "#c0c4cc", fontSize: 13, fontWeight: 400 },
                },
              }
        );
      }
    },

    // ------------------------------------------------------------------ 账号

    openAddAccount() {
      this.addDialog = {
        visible: true,
        platform: this.qrcodePlatforms.length ? this.qrcodePlatforms[0].key : "douyin",
        accountName: "",
      };
    },

    async submitAddAccount() {
      const accountName = (this.addDialog.accountName || "").trim();
      if (!accountName) {
        ElementPlus.ElMessage.warning("请填写账号名（自定义名称，用于区分不同账号）");
        return;
      }
      await this.startLogin(this.addDialog.platform, accountName);
      this.addDialog.visible = false;
    },

    async startLogin(platform, accountName) {
      try {
        const data = await this.api(`/api/accounts/${platform}/login`, {
          method: "POST",
          body: { account_name: accountName },
        });
        this.loginDialog = { visible: true, task: data.task, timer: null };
        this.pollLoginTask();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message);
      }
    },

    pollLoginTask() {
      this.loginDialog.timer = setInterval(async () => {
        try {
          const data = await this.api(`/api/tasks/${this.loginDialog.task.id}`);
          this.loginDialog.task = data.task;
          if (data.task.status === "success") {
            this.stopLoginPolling();
            ElementPlus.ElMessage.success("登录成功，cookie 已保存");
            this.loginDialog.visible = false;
            this.loadAccounts();
          }
        } catch (e) {
          this.stopLoginPolling();
        }
      }, 2000);
    },

    stopLoginPolling() {
      if (this.loginDialog.timer) {
        clearInterval(this.loginDialog.timer);
        this.loginDialog.timer = null;
      }
    },

    closeLoginDialog() {
      this.stopLoginPolling();
      this.loginDialog.visible = false;
    },

    async checkAccount(row) {
      const key = row.platform + "/" + row.account;
      this.checking = { ...this.checking, [key]: true };
      try {
        const data = await this.api(`/api/accounts/${row.platform}/${encodeURIComponent(row.account)}/check`, {
          method: "POST",
        });
        const taskId = data.task.id;
        const started = Date.now();
        const timer = setInterval(async () => {
          try {
            const result = await this.api(`/api/tasks/${taskId}`);
            const task = result.task;
            if (task.status === "success" || task.status === "failed") {
              clearInterval(timer);
              this.checking = { ...this.checking, [key]: false };
              if (task.status === "success") {
                ElementPlus.ElMessage.success(`${row.platform_name} · ${row.account}: ${task.message}`);
              } else {
                ElementPlus.ElMessage.error(`${row.platform_name} · ${row.account}: ${task.message}`);
              }
              this.loadTasks();
            } else if (Date.now() - started > 120000) {
              clearInterval(timer);
              this.checking = { ...this.checking, [key]: false };
            }
          } catch (e) {
            clearInterval(timer);
            this.checking = { ...this.checking, [key]: false };
          }
        }, 2000);
      } catch (e) {
        this.checking = { ...this.checking, [key]: false };
        ElementPlus.ElMessage.error(e.message);
      }
    },

    async removeAccount(row) {
      try {
        await ElementPlus.ElMessageBox.confirm(
          `确定删除账号 ${row.platform_name} · ${row.account} 吗？删除后需要重新扫码登录。`,
          "删除账号",
          { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" }
        );
      } catch (e) {
        return;
      }
      try {
        await this.api(`/api/accounts/${row.platform}/${encodeURIComponent(row.account)}`, { method: "DELETE" });
        ElementPlus.ElMessage.success("已删除");
        this.loadAccounts();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message);
      }
    },

    // ------------------------------------------------------------------ 上传 cookie

    openCookieDialog() {
      this.cookieDialog = {
        visible: true,
        platform: "bilibili",
        accountName: "",
        fileName: "",
        fileData: null,
        submitting: false,
      };
    },

    onPickCookieFile(event) {
      const file = event.target.files && event.target.files[0];
      event.target.value = "";
      if (!file) return;
      this.cookieDialog.fileName = file.name;
      this.cookieDialog.fileData = file;
    },

    async submitCookieUpload() {
      const dialog = this.cookieDialog;
      const accountName = (dialog.accountName || "").trim();
      if (!accountName) {
        ElementPlus.ElMessage.warning("请填写账号名");
        return;
      }
      if (!dialog.fileData) {
        ElementPlus.ElMessage.warning("请选择 cookie JSON 文件");
        return;
      }
      dialog.submitting = true;
      try {
        const fd = new FormData();
        fd.append("platform", dialog.platform);
        fd.append("account_name", accountName);
        fd.append("file", dialog.fileData);
        await this.api("/api/accounts/upload-cookie", { method: "POST", body: fd });
        dialog.visible = false;
        ElementPlus.ElMessage.success("cookie 已保存，正在验证登录态…");
        this.loadAccounts();
        // 上传后自动检查一次，结果以消息形式反馈
        setTimeout(() => {
          const row = this.accounts.find(
            (a) => a.platform === dialog.platform && a.account === accountName
          );
          if (row) this.checkAccount(row);
        }, 1500);
      } catch (e) {
        ElementPlus.ElMessage.error(e.message);
      } finally {
        dialog.submitting = false;
      }
    },

    // ------------------------------------------------------------------ 素材

    openPreview(material) {
      this.preview = { visible: true, type: material.type, name: material.name };
    },

    onDropFile(event) {
      this.dragover = false;
      const files = event.dataTransfer?.files || [];
      for (const file of files) this.uploadOne(file);
    },

    onPickFile(event) {
      const files = event.target.files || [];
      for (const file of files) this.uploadOne(file);
      event.target.value = "";
    },

    async uploadOne(file) {
      this.uploading = true;
      try {
        const fd = new FormData();
        fd.append("file", file);
        await this.api("/api/materials", { method: "POST", body: fd });
        ElementPlus.ElMessage.success(`已上传: ${file.name}`);
        this.loadMaterials();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message);
      } finally {
        this.uploading = false;
      }
    },

    async customUpload(option) {
      await this.uploadOne(option.file);
    },

    async removeMaterial(material) {
      try {
        await ElementPlus.ElMessageBox.confirm(`确定删除素材 ${material.name} 吗？`, "删除素材", {
          type: "warning",
          confirmButtonText: "删除",
          cancelButtonText: "取消",
        });
      } catch (e) {
        return;
      }
      try {
        await this.api(`/api/materials/${encodeURIComponent(material.name)}`, { method: "DELETE" });
        ElementPlus.ElMessage.success("已删除");
        this.loadMaterials();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message);
      }
    },

    // ------------------------------------------------------------------ 发布

    onPlatformChange() {
      this.form.contentType = "video";
      this.form.scheduleEnabled = false;
      this.form.scheduleTime = "";
    },

    async submitPublish() {
      const f = this.form;
      const spec = this.currentSpec;
      if (!f.accountName.trim()) {
        ElementPlus.ElMessage.warning("请填写或选择账号名");
        return;
      }
      if (!f.title.trim()) {
        ElementPlus.ElMessage.warning("请填写标题");
        return;
      }
      if (f.contentType === "video" && !f.file) {
        ElementPlus.ElMessage.warning("请选择视频素材");
        return;
      }
      if (f.contentType === "note" && (!f.images || !f.images.length)) {
        ElementPlus.ElMessage.warning("图文发布至少选择一张图片");
        return;
      }
      if (spec && spec.key === "bilibili" && !f.extras.tid) {
        ElementPlus.ElMessage.warning("请选择 Bilibili 分区");
        return;
      }
      if (f.scheduleEnabled && !f.scheduleTime) {
        ElementPlus.ElMessage.warning("已开启定时发布，请选择定时时间");
        return;
      }

      const payload = {
        platform: f.platform,
        content_type: f.contentType,
        account_name: f.accountName.trim(),
        file: f.file,
        images: f.images,
        title: f.title.trim(),
        desc: f.desc,
        note: f.note,
        tags: f.tags,
        publish_date: f.scheduleEnabled ? f.scheduleTime : "",
        thumbnail: f.thumbnail,
        thumbnail_landscape: f.thumbnailLandscape,
        thumbnail_portrait: f.thumbnailPortrait,
        headless: f.headless,
        extras: { ...f.extras },
      };

      this.submitting = true;
      try {
        const data = await this.api("/api/publish", { method: "POST", body: payload });
        ElementPlus.ElMessage.success(`任务已创建（${data.task.id}），可在任务记录中查看进度`);
        this.go("tasks");
      } catch (e) {
        ElementPlus.ElMessage.error(e.message);
      } finally {
        this.submitting = false;
      }
    },
  },

  watch: {
    route(newRoute) {
      if (newRoute === "dashboard") {
        this.loadAccounts();
        this.loadMaterials();
        this.loadTasks();
        this.loadStats();
        nextTick(() => this.renderCharts());
      } else {
        this.disposeCharts();
      }
    },
  },

  mounted() {
    this._charts = {};
    this._onResize = () => this.resizeCharts();
    window.addEventListener("resize", this._onResize);

    const applyHash = () => {
      const key = (location.hash || "#dashboard").replace("#", "");
      this.route = ROUTES.some((r) => r.key === key) ? key : "dashboard";
    };
    applyHash();
    window.addEventListener("hashchange", applyHash);

    this.loadMeta();
    this.loadAccounts();
    this.loadMaterials();
    this.loadTasks();
    this.loadStats();
    nextTick(() => this.renderCharts());
    this.tasksTimer = setInterval(() => {
      this.loadTasks();
      if (this.route === "dashboard") this.loadStats();
    }, 4000);
  },

  beforeUnmount() {
    if (this.tasksTimer) clearInterval(this.tasksTimer);
    this.stopLoginPolling();
    this.disposeCharts();
    window.removeEventListener("resize", this._onResize);
  },

  template: `
  <div class="layout">
    <aside class="sidebar">
      <div class="brand">
        <div class="logo"><span class="dot">🚀</span>social-auto-upload</div>
        <small>局域网发布管理台 v{{ meta.version }}</small>
      </div>
      <nav>
        <a v-for="r in routes" :key="r.key" href="#" :class="{ active: route === r.key }"
           @click.prevent="go(r.key)">{{ r.icon }} {{ r.label }}</a>
      </nav>
    </aside>

    <main class="main">
      <!-- ============================ 仪表盘 ============================ -->
      <div v-if="route === 'dashboard'">
        <div class="page-header">
          <h2 class="page-title">仪表盘</h2>
          <p class="page-subtitle">发布任务、账号与素材总览</p>
        </div>
        <div class="stat-grid">
          <div class="stat-card">
            <div class="icon-bubble" style="background:linear-gradient(135deg,#409eff,#5f7bff)">👤</div>
            <div>
              <div class="value">{{ stats ? Object.values(stats.accounts_by_platform).reduce((a,b)=>a+b,0) : accounts.length }}</div>
              <div class="label">已配置账号</div>
            </div>
          </div>
          <div class="stat-card">
            <div class="icon-bubble" style="background:linear-gradient(135deg,#7b5cff,#a78bfa)">🎬</div>
            <div>
              <div class="value">{{ stats ? stats.materials.video + stats.materials.image : materials.length }}</div>
              <div class="label">素材（视频 {{ stats ? stats.materials.video : '-' }} / 图片 {{ stats ? stats.materials.image : '-' }}）</div>
            </div>
          </div>
          <div class="stat-card">
            <div class="icon-bubble" style="background:linear-gradient(135deg,#ff9f40,#f8b422)">🚀</div>
            <div>
              <div class="value">{{ todayBucket.success + todayBucket.failed + todayBucket.other }}</div>
              <div class="label">今日任务 · 成功 {{ todayBucket.success }} / 失败 {{ todayBucket.failed }}</div>
            </div>
          </div>
          <div class="stat-card">
            <div class="icon-bubble" style="background:linear-gradient(135deg,#34c77b,#00c9a7)">📈</div>
            <div>
              <div class="value">{{ successRate }}</div>
              <div class="label">发布成功率（近期 {{ stats ? stats.tasks_total : 0 }} 个任务）</div>
            </div>
          </div>
        </div>

        <div class="chart-grid">
          <div class="card">
            <h3 class="card-title">📊 近 7 日任务趋势</h3>
            <div id="chart-trend" class="chart-box"></div>
          </div>
          <div class="card">
            <h3 class="card-title">🥧 平台任务分布</h3>
            <div id="chart-platform" class="chart-box"></div>
          </div>
        </div>

        <div class="card">
          <h3 class="card-title">🌐 平台能力</h3>
          <el-table :data="meta.platforms" size="small">
            <el-table-column label="平台" width="150">
              <template #default="{ row }">
                <span style="margin-right:6px">{{ platformIcon(row.key) }}</span>{{ row.name }}
              </template>
            </el-table-column>
            <el-table-column label="登录方式" width="120">
              <template #default="{ row }">
                <el-tag v-if="row.login_mode === 'qrcode'" type="success" size="small" effect="light">网页扫码</el-tag>
                <el-tag v-else type="warning" size="small" effect="light">本地终端</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="视频" width="70">
              <template #default="{ row }">✅</template>
            </el-table-column>
            <el-table-column label="图文" width="70">
              <template #default="{ row }">{{ row.supports_note ? '✅' : '—' }}</template>
            </el-table-column>
            <el-table-column label="账号数" width="80">
              <template #default="{ row }">{{ stats && stats.accounts_by_platform[row.key] !== undefined ? stats.accounts_by_platform[row.key] : 0 }}</template>
            </el-table-column>
            <el-table-column label="说明" min-width="260">
              <template #default="{ row }">
                <span v-if="row.login_mode === 'terminal'" class="mono">{{ row.terminal_login_hint }}</span>
                <span v-else style="color:#909399">在账号管理页扫码登录</span>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>

      <!-- ============================ 账号管理 ============================ -->
      <div v-if="route === 'accounts'">
        <div class="page-header">
          <h2 class="page-title">账号管理</h2>
          <p class="page-subtitle">一个账号名对应一个 cookie 文件（cookies/<平台>_<账号名>.json）</p>
        </div>
        <div class="card">
          <div class="toolbar">
            <div style="display:flex;gap:10px;flex-wrap:wrap">
              <el-button type="primary" @click="openAddAccount">＋ 扫码登录 / 添加账号</el-button>
              <el-button type="success" plain @click="openCookieDialog">⬆ 上传 cookie（Bilibili / YouTube）</el-button>
            </div>
            <el-button @click="loadAccounts">刷新</el-button>
          </div>
          <el-table :data="accounts" empty-text="暂无账号，点击右上角扫码登录添加">
            <el-table-column label="平台" width="150">
              <template #default="{ row }">
                <span style="margin-right:6px">{{ platformIcon(row.platform) }}</span>{{ row.platform_name }}
              </template>
            </el-table-column>
            <el-table-column prop="account" label="账号名" min-width="140" />
            <el-table-column prop="updated_at" label="cookie 更新时间" width="180" />
            <el-table-column label="操作" width="280">
              <template #default="{ row }">
                <el-button size="small" :loading="checking[row.platform + '/' + row.account]" @click="checkAccount(row)">检查</el-button>
                <el-button size="small" type="primary" plain v-if="isQrPlatform(row.platform)" @click="startLogin(row.platform, row.account)">重新扫码</el-button>
                <el-button size="small" type="danger" plain @click="removeAccount(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>

      <!-- ============================ 素材库（画廊） ============================ -->
      <div v-if="route === 'materials'">
        <div class="page-header">
          <h2 class="page-title">素材库</h2>
          <p class="page-subtitle">保存在服务器 uploadFile/ 目录；点击卡片可预览视频或图片</p>
        </div>

        <div class="upload-drop" :class="{ dragover }"
             @click="$refs.fileInput.click()"
             @dragover.prevent="dragover = true"
             @dragleave.prevent="dragover = false"
             @drop.prevent="onDropFile">
          <div style="font-size:26px">{{ uploading ? '⏳' : '⬆️' }}</div>
          <div style="margin-top:6px;font-size:13px">
            {{ uploading ? '正在上传…' : '点击或拖拽视频 / 图片到此处上传' }}
          </div>
          <div style="margin-top:4px;font-size:11.5px;opacity:.75">
            支持 mp4 / mov / avi / mkv / m4v / webm / flv / wmv / jpg / png / webp 等
          </div>
          <input ref="fileInput" type="file" multiple hidden
                 accept=".mp4,.mov,.avi,.mkv,.m4v,.webm,.flv,.wmv,.jpg,.jpeg,.png,.webp,.bmp"
                 @change="onPickFile" />
        </div>

        <div class="gallery" style="margin-top:16px" v-if="materials.length">
          <div class="media-card" v-for="m in materials" :key="m.name">
            <div class="cover" @click="openPreview(m)">
              <img :src="posterUrl(m.name)" loading="lazy" :alt="m.name" />
              <div class="play-badge" v-if="m.type === 'video'"><div class="circle">▶</div></div>
              <span class="duration" v-if="m.type === 'video' && m.duration">{{ fmtDuration(m.duration) }}</span>
            </div>
            <div class="body">
              <div class="name" :title="m.name">{{ m.name }}</div>
              <div class="meta-row">
                <span class="type-chip" :class="m.type">{{ m.type === 'video' ? '视频' : '图片' }}</span>
                <span class="meta">{{ fmtSize(m.size) }}</span>
                <el-button size="small" text type="danger" @click.stop="removeMaterial(m)">删除</el-button>
              </div>
            </div>
          </div>
        </div>
        <el-empty v-else description="暂无素材，拖拽或点击上方区域上传" :image-size="90" style="background:#fff;border-radius:12px;padding:36px 0" />
      </div>

      <!-- ============================ 发布任务 ============================ -->
      <div v-if="route === 'publish'">
        <div class="page-header">
          <h2 class="page-title">发布任务</h2>
          <p class="page-subtitle">任务进入队列后逐个执行（并发 {{ meta.upload_concurrency || 1 }}），右侧实时预览发布效果</p>
        </div>
        <div class="publish-layout">
          <div class="card">
            <el-form label-width="110px">
              <el-form-item label="平台">
                <el-select v-model="form.platform" @change="onPlatformChange" style="width: 240px">
                  <el-option v-for="p in meta.platforms" :key="p.key" :value="p.key" :label="platformIcon(p.key) + '  ' + p.name" />
                </el-select>
              </el-form-item>

              <el-form-item label="内容类型" v-if="currentSpec && currentSpec.supports_note">
                <el-radio-group v-model="form.contentType">
                  <el-radio value="video">视频</el-radio>
                  <el-radio value="note">图文</el-radio>
                </el-radio-group>
              </el-form-item>

              <el-form-item label="账号名">
                <el-select v-model="form.accountName" filterable allow-create default-first-option
                           placeholder="选择已有账号或输入新账号名" style="width: 320px">
                  <el-option v-for="a in platformAccounts" :key="a.account" :value="a.account" :label="a.account + '（已有cookie）'" />
                </el-select>
                <div style="font-size:12px;color:#909399;line-height:1.6;margin-top:6px;max-width:480px">
                  没有可选账号时，先到「账号管理」扫码登录
                  <span v-if="currentSpec && currentSpec.login_mode === 'terminal'">（{{ currentSpec.name }}需在服务器终端登录）</span>
                </div>
              </el-form-item>

              <el-form-item label="视频素材" v-if="form.contentType === 'video'">
                <el-select v-model="form.file" filterable allow-create default-first-option
                           placeholder="从素材库选择，或输入服务器绝对路径" style="width: 480px">
                  <el-option v-for="m in videoMaterials" :key="m.name" :value="m.name"
                             :label="m.name + '（' + fmtDuration(m.duration || 0) + ' · ' + fmtSize(m.size) + '）'" />
                </el-select>
              </el-form-item>

              <el-form-item label="图片素材" v-if="form.contentType === 'note'">
                <el-select v-model="form.images" multiple filterable
                           placeholder="从素材库选择图片（可多选）" style="width: 480px">
                  <el-option v-for="m in imageMaterials" :key="m.name" :value="m.name" :label="m.name" />
                </el-select>
              </el-form-item>

              <el-form-item label="标题" required>
                <el-input v-model="form.title" maxlength="100" show-word-limit style="width: 480px" />
              </el-form-item>

              <el-form-item label="简介" v-if="form.contentType === 'video'">
                <el-input v-model="form.desc" type="textarea" :rows="3" placeholder="视频描述（可留空）" style="width: 480px" />
              </el-form-item>

              <el-form-item label="图文正文" v-if="form.contentType === 'note'">
                <el-input v-model="form.note" type="textarea" :rows="4" placeholder="图文正文内容" style="width: 480px" />
              </el-form-item>

              <el-form-item label="标签">
                <el-input v-model="form.tags" placeholder="逗号分隔，如: vlog,日常,教程" style="width: 480px" />
              </el-form-item>

              <el-form-item label="发布时间">
                <div>
                  <template v-if="!currentSpec || currentSpec.supports_schedule">
                    <el-switch v-model="form.scheduleEnabled" active-text="定时发布" inactive-text="立即发布" />
                    <div v-if="form.scheduleEnabled" style="margin-top:8px">
                      <el-date-picker v-model="form.scheduleTime" type="datetime"
                                      value-format="YYYY-MM-DD HH:mm" format="YYYY-MM-DD HH:mm"
                                      placeholder="选择定时时间" style="width: 240px" />
                      <div style="font-size:12px;color:#909399">定时时间须晚于当前时间至少 2 小时（平台侧定时，到点由平台自动发出）</div>
                    </div>
                  </template>
                  <template v-else>
                    <el-tag type="info" effect="plain" size="small">仅支持立即发布</el-tag>
                    <div style="font-size:12px;color:#909399;margin-top:4px">该平台未接入定时发布（支持定时的平台：抖音、快手、小红书、Bilibili、视频号）</div>
                  </template>
                </div>
              </el-form-item>

              <el-form-item label="封面图">
                <el-select v-model="form.thumbnail" filterable clearable placeholder="可选" style="width: 320px">
                  <el-option v-for="m in imageMaterials" :key="m.name" :value="m.name" :label="m.name" />
                </el-select>
              </el-form-item>

              <el-form-item label="横版封面" v-if="form.contentType === 'video' && (form.platform === 'douyin' || form.platform === 'tencent')">
                <el-select v-model="form.thumbnailLandscape" filterable clearable placeholder="可选，4:3 横版封面" style="width: 320px">
                  <el-option v-for="m in imageMaterials" :key="m.name" :value="m.name" :label="m.name" />
                </el-select>
              </el-form-item>

              <el-form-item label="竖版封面" v-if="form.contentType === 'video' && (form.platform === 'douyin' || form.platform === 'tencent')">
                <el-select v-model="form.thumbnailPortrait" filterable clearable placeholder="可选，3:4 竖版封面（未填时用封面图）" style="width: 320px">
                  <el-option v-for="m in imageMaterials" :key="m.name" :value="m.name" :label="m.name" />
                </el-select>
              </el-form-item>

              <el-form-item label="原创声明" v-if="form.platform === 'douyin' && form.contentType === 'video'">
                <el-input v-model="form.extras.declaration" placeholder="留空则默认声明「内容由AI生成」；填写须与平台选项文字完全一致" style="width: 420px" />
              </el-form-item>

              <el-form-item label="商品链接" v-if="form.platform === 'douyin' && form.contentType === 'video'">
                <div style="display:flex;flex-direction:column;gap:10px">
                  <el-input v-model="form.extras.product_link" placeholder="可选，带货商品链接" style="width: 420px" />
                  <el-input v-model="form.extras.product_title" placeholder="商品标题（挂链接时必填）" style="width: 420px" />
                </div>
              </el-form-item>

              <el-form-item label="Bilibili分区" v-if="form.platform === 'bilibili'">
                <el-select v-model="form.extras.tid" filterable placeholder="选择分区" style="width: 320px">
                  <el-option v-for="z in meta.zones.bilibili_tid" :key="z.value" :value="z.value" :label="z.label" />
                </el-select>
              </el-form-item>

              <el-form-item label="可见性" v-if="form.platform === 'youtube'">
                <el-select v-model="form.extras.visibility" style="width: 220px">
                  <el-option value="public" label="公开 public" />
                  <el-option value="unlisted" label="不公开列出 unlisted" />
                  <el-option value="private" label="私享 private" />
                </el-select>
              </el-form-item>

              <el-form-item label="播放列表" v-if="form.platform === 'youtube'">
                <el-input v-model="form.extras.playlist" placeholder="可选，加入播放列表（须已存在）" style="width: 320px" />
              </el-form-item>

              <el-form-item label="视频号选项" v-if="form.platform === 'tencent'">
                <div style="display:flex;flex-direction:column;gap:10px">
                  <el-select v-model="form.extras.category" filterable clearable placeholder="可选，内容分类" style="width: 240px">
                    <el-option v-for="z in meta.zones.tencent_category" :key="z.value" :value="z.value" :label="z.label" />
                  </el-select>
                  <el-input v-model="form.extras.short_title" placeholder="可选，短标题" style="width: 320px" />
                  <el-switch v-model="form.extras.is_draft" active-text="存草稿（不发布）" />
                </div>
              </el-form-item>

              <el-form-item label="合集" v-if="currentSpec && currentSpec.extra_fields.includes('collection_name')">
                <el-input v-model="form.extras.collection_name" placeholder="可选，加入合集（须已在平台存在）" style="width: 320px" />
              </el-form-item>

              <el-form-item label="背景音乐" v-if="form.platform === 'douyin' && form.contentType === 'note'">
                <el-input v-model="form.extras.bgm" placeholder="可选，抖音图文BGM" style="width: 320px" />
              </el-form-item>

              <el-form-item label="浏览器模式">
                <el-switch v-model="form.headless" active-text="无头模式（推荐）" inactive-text="有头模式" />
                <div style="font-size:12px;color:#909399;margin-top:6px">服务器无显示器时请保持无头模式</div>
              </el-form-item>

              <el-form-item>
                <el-button type="primary" size="large" :loading="submitting" @click="submitPublish">🚀 提交发布任务</el-button>
              </el-form-item>
            </el-form>
          </div>

          <!-- 实时发布预览 -->
          <div class="preview-card">
            <h3 class="card-title">📱 发布预览</h3>
            <div class="preview-phone">
              <div class="ph-cover" :style="previewCover ? { backgroundImage: 'url(' + previewCover + ')', backgroundSize: 'cover' } : {}">
                <span v-if="!previewCover">🎬</span>
              </div>
              <div class="ph-body">
                <div class="ph-platform">
                  <span>{{ platformIcon(form.platform) }} {{ platformName(form.platform) }} · {{ form.contentType === 'note' ? '图文' : '视频' }}</span>
                  <span>@{{ form.accountName || '账号名' }}</span>
                </div>
                <div class="ph-title">{{ form.title || '（标题将显示在这里）' }}</div>
                <div class="ph-desc" v-if="previewDesc">{{ previewDesc }}</div>
                <div class="ph-tags" v-if="previewTagList.length">
                  <span v-for="tag in previewTagList" :key="tag"># {{ tag }}</span>
                </div>
                <div class="ph-schedule" v-if="form.scheduleEnabled && form.scheduleTime">
                  ⏰ 定时发布 · {{ form.scheduleTime }}
                </div>
              </div>
            </div>
            <div style="font-size:11.5px;color:#c0c4cc;margin-top:10px;text-align:center">
              预览仅供参考，实际样式以平台为准
            </div>
          </div>
        </div>
      </div>

      <!-- ============================ 任务记录 ============================ -->
      <div v-if="route === 'tasks'">
        <div class="page-header">
          <h2 class="page-title">任务记录</h2>
          <p class="page-subtitle">
            每 4 秒自动刷新<span v-if="hasRunningTasks"> · 有任务执行中…</span>（任务记录保存在内存中，服务重启后清空）
          </p>
        </div>
        <div class="card">
          <div class="toolbar">
            <el-radio-group v-model="taskFilter">
              <el-radio-button value="">全部</el-radio-button>
              <el-radio-button value="upload">发布</el-radio-button>
              <el-radio-button value="login">登录</el-radio-button>
              <el-radio-button value="check">检查</el-radio-button>
            </el-radio-group>
            <el-button @click="loadTasks">刷新</el-button>
          </div>
          <el-table :data="filteredTasks" empty-text="暂无任务">
            <el-table-column label="封面" width="90">
              <template #default="{ row }">
                <img v-if="row.file && !row.file.includes('/') && !row.file.includes(',')"
                     class="task-thumb" :src="posterUrl(row.file)" loading="lazy" />
                <span v-else style="font-size:18px">{{ platformIcon(row.platform) }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" width="165" />
            <el-table-column label="类型" width="95">
              <template #default="{ row }">{{ taskTypeLabel(row.type) }}</template>
            </el-table-column>
            <el-table-column label="平台" width="110">
              <template #default="{ row }">{{ platformIcon(row.platform) }} {{ platformName(row.platform) }}</template>
            </el-table-column>
            <el-table-column prop="account" label="账号" min-width="110" />
            <el-table-column prop="summary" label="内容" min-width="200" show-overflow-tooltip />
            <el-table-column label="状态" width="150">
              <template #default="{ row }">
                <el-tag :type="statusTagType(row.status)" size="small" effect="light">{{ statusLabel(row.status) }}</el-tag>
                <el-tag v-if="row.waiting_verify_code" type="danger" size="small" effect="dark" style="margin-left:4px">📱待验证码</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="信息" min-width="220">
              <template #default="{ row }">
                <div style="display:flex;align-items:center;gap:8px">
                  <div style="flex:1;min-width:0">
                    <div v-if="row.status === 'failed'" class="error-text">{{ row.error || row.message }}</div>
                    <div v-else style="font-size:13px;color:#606266">{{ row.message }}</div>
                  </div>
                  <el-button v-if="row.waiting_verify_code" size="small" type="danger" plain @click="promptVerifyCode(row)">输入验证码</el-button>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </main>

    <!-- 添加账号 -->
    <el-dialog v-model="addDialog.visible" title="扫码登录 / 添加账号" width="460px">
      <el-form label-width="80px">
        <el-form-item label="平台">
          <el-select v-model="addDialog.platform" style="width: 240px">
            <el-option v-for="p in qrcodePlatforms" :key="p.key" :value="p.key" :label="platformIcon(p.key) + '  ' + p.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="账号名">
          <el-input v-model="addDialog.accountName" placeholder="自定义账号名（如 main / 小号2）" />
        </el-form-item>
      </el-form>
      <div class="hint-box">
        Bilibili / YouTube 登录需要在服务器本地终端执行 sau 命令，此处仅支持扫码登录的平台。
      </div>
      <template #footer>
        <el-button @click="addDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="submitAddAccount">打开登录二维码</el-button>
      </template>
    </el-dialog>

    <!-- 上传 cookie -->
    <el-dialog v-model="cookieDialog.visible" title="上传 cookie 文件" width="520px">
      <el-form label-width="90px">
        <el-form-item label="平台">
          <el-select v-model="cookieDialog.platform" style="width: 240px">
            <el-option v-for="p in meta.platforms" :key="p.key" :value="p.key" :label="platformIcon(p.key) + '  ' + p.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="账号名">
          <el-input v-model="cookieDialog.accountName" placeholder="与登录时使用的账号名一致" />
        </el-form-item>
        <el-form-item label="cookie文件">
          <div class="upload-drop" style="padding:14px" @click="$refs.cookieFileInput.click()">
            <div style="font-size:13px">{{ cookieDialog.fileName || '点击选择 cookie JSON 文件' }}</div>
            <div v-if="cookieDialog.fileName" style="font-size:11.5px;opacity:.75;margin-top:3px">已选择，可点击重新选择</div>
            <input ref="cookieFileInput" type="file" hidden accept=".json,application/json" @change="onPickCookieFile" />
          </div>
        </el-form-item>
      </el-form>
      <div class="hint-box">
        适用：Bilibili / YouTube（无法网页扫码）以及跨机器迁移登录态。<br />
        在任意装有本项目的电脑上执行 <span class="mono">sau &lt;平台&gt; login --account &lt;账号名&gt;</span>，
        然后上传该项目 <span class="mono">cookies/&lt;平台&gt;_&lt;账号名&gt;.json</span> 文件。
        同名账号会被覆盖；上传后将自动验证登录态。
      </div>
      <template #footer>
        <el-button @click="cookieDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="cookieDialog.submitting" @click="submitCookieUpload">上传并验证</el-button>
      </template>
    </el-dialog>

    <!-- 扫码登录二维码 -->
    <el-dialog :model-value="loginDialog.visible" title="扫码登录" width="380px" :close-on-click-modal="false"
               @close="closeLoginDialog">
      <div class="qr-box" v-if="loginDialog.task">
        <div style="font-size:14px">
          {{ platformIcon(loginDialog.task.platform) }} {{ platformName(loginDialog.task.platform) }} · {{ loginDialog.task.account }}
        </div>
        <img v-if="loginDialog.task.qrcode_data_url" :src="loginDialog.task.qrcode_data_url" alt="登录二维码" />
        <div v-else class="qr-spinner"></div>
        <div style="font-size:13px;color:#606266">{{ loginDialog.task.message }}</div>
        <div v-if="loginDialog.task.status === 'failed'" class="error-text">{{ loginDialog.task.error }}</div>
      </div>
      <template #footer>
        <el-button @click="closeLoginDialog">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 素材预览：视频播放器 / 图片灯箱 -->
    <el-dialog :model-value="preview.visible" :title="preview.name" width="760px" @close="preview.visible = false">
      <div class="preview-body">
        <video v-if="preview.type === 'video'" :src="materialUrl(preview.name)" controls autoplay></video>
        <img v-else class="full" :src="materialUrl(preview.name)" :alt="preview.name" />
      </div>
    </el-dialog>
  </div>
`,
});

app.use(ElementPlus, { locale: ElementPlusLocaleZhCn });
app.mount("#app");
