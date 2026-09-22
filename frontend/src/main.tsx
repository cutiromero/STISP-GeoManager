import { App as AntdApp, ConfigProvider } from "antd";
import enUS from "antd/locale/en_US";
import zhCN from "antd/locale/zh_CN";
import dayjs from "dayjs";
import "dayjs/locale/en";
import "dayjs/locale/zh-cn";
import React from "react";
import ReactDOM from "react-dom/client";
import { useTranslation } from "react-i18next";
import { BrowserRouter } from "react-router-dom";
import "antd/dist/reset.css";
import "./styles.css";
import "./styles/about-v2.css";
import App from "./App";
import "./i18n";
import { currentLocale } from "./i18n";
import { appTheme } from "./theme";

function LocalizedApplication() {
  const { i18n } = useTranslation();
  const locale = currentLocale();
  const antdLocale = locale === "en-US" ? enUS : zhCN;
  dayjs.locale(locale === "en-US" ? "en" : "zh-cn");
  document.documentElement.lang = locale;

  return (
    <ConfigProvider locale={antdLocale} theme={appTheme}>
      <AntdApp>
        <BrowserRouter>
          <App locale={locale} languageVersion={i18n.resolvedLanguage} />
        </BrowserRouter>
      </AntdApp>
    </ConfigProvider>
  );
}

const rootElement = document.getElementById("root");
if (rootElement) {
  ReactDOM.createRoot(rootElement).render(
    <React.StrictMode>
      <LocalizedApplication />
    </React.StrictMode>,
  );
}
