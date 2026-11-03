(function () {
  "use strict";
  function showDetails() {
    var notice = document.getElementById("startup-notice");
    if (!notice) return;
    var missing = [];
    if (!window.fetch) missing.push("网络请求");
    if (!window.AbortController) missing.push("请求取消");
    if (!window.Promise) missing.push("异步任务");
    if (!window.URL) missing.push("地址解析");
    var information = document.createElement("p");
    information.textContent = missing.length
      ? "浏览器缺少所需功能：" +
        missing.join("、") +
        "。请升级 Chrome 或 Edge 后重试。"
      : "页面尚未完成加载。可能是网络、浏览器兼容或旧缓存问题，请刷新重试；若再次发生，请将下方浏览器信息提供给管理员。";
    notice.appendChild(information);
    var details = document.createElement("details");
    var summary = document.createElement("summary");
    summary.textContent = "浏览器信息";
    var text = document.createElement("p");
    text.style.wordBreak = "break-all";
    text.textContent = navigator.userAgent;
    details.appendChild(summary);
    details.appendChild(text);
    notice.appendChild(details);
    var reload = document.createElement("button");
    reload.textContent = "重新加载";
    reload.addEventListener("click", function () {
      window.location.reload();
    });
    notice.appendChild(reload);
  }
  window.setTimeout(showDetails, 15000);
})();
