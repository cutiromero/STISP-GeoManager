import {
  Component,
  lazy,
  useEffect,
  useState,
  type ComponentType,
  type ErrorInfo,
  type ReactNode,
} from "react";
import { Link, useLocation } from "react-router-dom";
import { currentLocale } from "../i18n";
import { downloadPageDiagnostics, recordPageError } from "./pageDiagnostics";
import "./pageRecovery.css";

const failedLoads = new Set<() => void>();

/** React.lazy caches a rejection; recreate only failed loaders on explicit retry. */
export function lazyPage<P extends object>(
  load: () => Promise<{ default: ComponentType<P> }>,
) {
  const create = () =>
    lazy(() =>
      load().catch((error: unknown) => {
        failedLoads.add(reset);
        throw error;
      }),
    );
  const reset = () => {
    Page = create();
    failedLoads.delete(reset);
  };
  let Page = create();
  return function ReloadablePage(props: P) {
    return <Page {...props} />;
  };
}

export function retryFailedPageLoads() {
  for (const reset of failedLoads) reset();
}

export function isPageChunkError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error);
  return /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module|Loading (?:CSS )?chunk|Unable to preload CSS/i.test(
    message,
  );
}

function asPageError(error: unknown) {
  return error instanceof Error ? error : new Error(String(error));
}

type BoundaryProps = {
  children: ReactNode;
  resetKey?: string;
  path?: string;
  onRetry?: () => void;
  navigation?: ReactNode;
};
type BoundaryState = { error: Error | null; resetKey?: string };

export class ApplicationErrorBoundary extends Component<
  BoundaryProps,
  BoundaryState
> {
  state: BoundaryState = { error: null, resetKey: this.props.resetKey };

  static getDerivedStateFromProps(props: BoundaryProps, state: BoundaryState) {
    return props.resetKey !== state.resetKey
      ? { error: null, resetKey: props.resetKey }
      : null;
  }

  static getDerivedStateFromError(error: unknown) {
    return { error: asPageError(error) };
  }

  componentDidCatch(caught: unknown, info: ErrorInfo) {
    const error = asPageError(caught);
    console.error("Platform page failed", error, info.componentStack);
    recordPageError(error, info.componentStack, this.props.path);
  }

  render() {
    const error = this.state.error;
    if (!error) return this.props.children;
    const en = currentLocale() === "en-US";
    const chunk = isPageChunkError(error);
    return (
      <section className="page-recovery" role="alert">
        <header className="page-recovery-nav">
          <strong>STISP</strong>
          {this.props.navigation ?? (
            <a href="/map">{en ? "Map workspace" : "地理工作台"}</a>
          )}
        </header>
        <main className="page-recovery-content">
          <h1>
            {chunk
              ? en
                ? "This page could not be loaded"
                : "页面资源加载失败"
              : en
                ? "This page encountered a problem"
                : "当前页面出现异常"}
          </h1>
          <p>
            {chunk
              ? en
                ? "A connection interruption or platform update may have affected loading. Reload to obtain the current page."
                : "网络中断或平台更新可能影响了资源加载，请重新加载页面。"
              : en
                ? "You can retry this page or open another module. Saved conversations and tasks remain available."
                : "可以重试当前页面或进入其他模块，已保存的对话和任务仍可重新打开。"}
          </p>
          <div className="page-recovery-actions">
            {this.props.onRetry && (
              <button
                type="button"
                onClick={() => {
                  retryFailedPageLoads();
                  this.props.onRetry?.();
                  this.setState({ error: null });
                }}
              >
                {en ? "Retry page" : "重试当前页面"}
              </button>
            )}
            <button type="button" onClick={() => window.location.reload()}>
              {en ? "Reload platform" : "重新加载平台"}
            </button>
            <button
              type="button"
              onClick={() => downloadPageDiagnostics(error)}
            >
              {en ? "Download diagnostics" : "导出诊断"}
            </button>
          </div>
          <p>
            {en
              ? "Diagnostics are collected automatically. Send the exported file to the administrator."
              : "已自动记录异常位置和接口信息，可导出文件交给管理员。"}
          </p>
          <details>
            <summary>{en ? "Error details" : "异常信息"}</summary>
            <pre>{`${error.name}: ${error.message}`}</pre>
          </details>
        </main>
      </section>
    );
  }
}

export function RouteRecovery({ children }: { children: ReactNode }) {
  const location = useLocation();
  const [attempt, setAttempt] = useState(0);
  const en = currentLocale() === "en-US";
  useEffect(() => {
    retryFailedPageLoads();
  }, [location.key]);
  return (
    <ApplicationErrorBoundary
      resetKey={`${location.pathname}:${location.key}`}
      path={location.pathname}
      onRetry={() => setAttempt((value) => value + 1)}
      navigation={
        <nav aria-label={en ? "Recovery navigation" : "页面恢复导航"}>
          <Link to="/map">{en ? "Map workspace" : "地理工作台"}</Link>
          <Link to="/agent/chat">{en ? "Quick chat" : "快速对话"}</Link>
          <Link to="/agent/workbench">
            {en ? "Research agent" : "科研智能体"}
          </Link>
        </nav>
      }
    >
      <div key={attempt} style={{ height: "100%" }}>
        {children}
      </div>
    </ApplicationErrorBoundary>
  );
}
