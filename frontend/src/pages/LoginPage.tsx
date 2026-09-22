import {
  DatabaseOutlined,
  DeploymentUnitOutlined,
  EnvironmentOutlined,
  FundProjectionScreenOutlined,
  LockOutlined,
  LoginOutlined,
  SafetyCertificateOutlined,
  UserAddOutlined,
  UserOutlined,
  UserSwitchOutlined,
} from "@ant-design/icons";
import {
  Alert,
  App,
  BorderBeam,
  Button,
  Card,
  Checkbox,
  Form,
  Input,
  Radio,
  Typography,
} from "antd";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import capfedLogoWhite from "../assets/capfed-logo-white.svg";
import loginBackground01 from "../assets/spatiotemporal/digital-city.png";
import loginBackground02 from "../assets/spatiotemporal/digital-earth.png";
import loginBackground03 from "../assets/spatiotemporal/data-layers.png";
import { teamInstitution } from "../about/institution";
import { oceanBorderBeam } from "../components/oceanBorderBeam";
import LanguageSwitcher from "../components/LanguageSwitcher";
import { platformBrand } from "../config/platformBrand";
import { useAppContext } from "../contexts/AppContext";
import { currentLocale } from "../i18n";
import type {
  LoginFormValues,
  LoginOverviewResponse,
  LoginOverviewStatus,
  RegisterFormValues,
} from "../types";

const platformChineseName = platformBrand.chineseName;
const platformEnglishName = platformBrand.englishName;
const platformShortName = platformBrand.shortName;
const platformEdition = platformBrand.edition;
const platformVersion = "v1.0.0";
const loginBackgrounds = [
  loginBackground01,
  loginBackground02,
  loginBackground03,
] as const;
const loginBackgroundIntervalMs = 9000;
const loginBackgroundTransitionMs = 1600;

function fallbackLoginStats(t: (key: string) => string) {
  return [
    {
      id: "dataResources",
      icon: <DatabaseOutlined style={{ fontSize: 18 }} />,
      label: t("auth.platformResources"),
      note: t("auth.statisticsUnavailableShort"),
      value: 0,
      displayValue: "--",
    },
    {
      id: "thematicLayers",
      icon: <FundProjectionScreenOutlined style={{ fontSize: 18 }} />,
      label: t("auth.thematicLayers"),
      note: t("auth.statisticsUnavailableShort"),
      value: 0,
      displayValue: "--",
    },
    {
      id: "monitoringSites",
      icon: <DeploymentUnitOutlined style={{ fontSize: 18 }} />,
      label: t("auth.monitoringSites"),
      note: t("auth.statisticsUnavailableShort"),
      value: 0,
      displayValue: "--",
    },
    {
      id: "coveredBasins",
      icon: <EnvironmentOutlined style={{ fontSize: 18 }} />,
      label: t("auth.coveredBasins"),
      note: t("auth.statisticsUnavailableShort"),
      value: 0,
      displayValue: "--",
    },
  ];
}

function metricIcon(metricId: string) {
  const style = { fontSize: 18 };
  if (metricId === "dataResources") return <DatabaseOutlined style={style} />;
  if (metricId === "thematicLayers") {
    return <FundProjectionScreenOutlined style={style} />;
  }
  if (metricId === "monitoringSites") {
    return <DeploymentUnitOutlined style={style} />;
  }
  return <EnvironmentOutlined style={style} />;
}

function serviceNodes(overview: LoginOverviewResponse | null) {
  if (!overview) return [];
  return overview.serviceStatus.nodeSummary.legend.flatMap((item) =>
    Array.from({ length: item.count }, (_, index) => ({
      id: `${item.status}-${index + 1}`,
      state: item.status as LoginOverviewStatus,
    })),
  );
}

export default function LoginPage() {
  const { bootstrap, setUser } = useAppContext();
  const { message, modal } = App.useApp();
  const { t } = useTranslation();
  const locale = currentLocale();
  const [submittingAction, setSubmittingAction] = useState<
    "login" | "register" | "guest" | null
  >(null);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [accountPurpose, setAccountPurpose] =
    useState<RegisterFormValues["accountPurpose"]>("standard");
  const [overview, setOverview] = useState<LoginOverviewResponse | null>(null);
  const [activeBackgroundIndex, setActiveBackgroundIndex] = useState(0);
  const [outgoingBackgroundIndex, setOutgoingBackgroundIndex] = useState<
    number | null
  >(null);
  const isSubmitting = submittingAction !== null;

  useEffect(() => {
    let mounted = true;
    api
      .loginOverview()
      .then((result) => {
        if (mounted) setOverview(result);
      })
      .catch(() => {
        if (mounted) setOverview(null);
      });
    return () => {
      mounted = false;
    };
  }, [locale]);

  useEffect(() => {
    const rotationId = window.setTimeout(() => {
      setOutgoingBackgroundIndex(activeBackgroundIndex);
      setActiveBackgroundIndex(
        (activeBackgroundIndex + 1) % loginBackgrounds.length,
      );
    }, loginBackgroundIntervalMs);

    return () => window.clearTimeout(rotationId);
  }, [activeBackgroundIndex]);

  useEffect(() => {
    if (outgoingBackgroundIndex === null) return;

    const transitionId = window.setTimeout(() => {
      setOutgoingBackgroundIndex(null);
    }, loginBackgroundTransitionMs);

    return () => window.clearTimeout(transitionId);
  }, [outgoingBackgroundIndex]);

  const loginStats = useMemo(
    () =>
      overview?.metrics.map((metric) => ({
        ...metric,
        icon: metricIcon(metric.id),
      })) ?? fallbackLoginStats(t),
    [overview, t],
  );
  const fallbackCapabilityTags = [
    t("auth.remoteSensing"),
    t("auth.vectorBoundary"),
    t("auth.fieldPlots"),
    t("auth.longTermMonitoring"),
    t("auth.thematicSharing"),
  ];
  const capabilityTags =
    overview?.hero.capabilityTags ?? fallbackCapabilityTags;
  const primaryPlatformName =
    locale === "en-US" ? platformEnglishName : platformChineseName;
  const secondaryPlatformName =
    locale === "en-US" ? platformChineseName : platformEnglishName;
  const stationStatuses = useMemo(() => serviceNodes(overview), [overview]);
  const serviceStatusSummary = overview?.serviceStatus.nodeSummary.legend ?? [];

  async function handleFinish(values: LoginFormValues) {
    setSubmittingAction("login");
    try {
      await api.csrf();
      const response = await api.login(
        values.username,
        values.password,
        Boolean(values.remember),
      );
      setUser(response.user);
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("auth.loginFailed"),
      );
      setSubmittingAction(null);
    }
  }

  async function handleRegister(values: RegisterFormValues) {
    setSubmittingAction("register");
    try {
      await api.csrf();
      const response = await api.register(values);
      message.success(response.detail);
      setUser(response.user);
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("auth.registerFailed"),
      );
      setSubmittingAction(null);
    }
  }

  function handleForgotPassword() {
    modal.info({
      title: t("auth.contactAdminTitle"),
      content: t("auth.contactAdminDescription"),
      okText: t("auth.understood"),
    });
  }

  async function handleGuestLogin() {
    setSubmittingAction("guest");
    try {
      await api.csrf();
      const response = await api.guestLogin();
      setUser(response.user);
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("auth.guestLoginFailed"),
      );
      setSubmittingAction(null);
    }
  }

  return (
    <main className="login-shell">
      <LanguageSwitcher className="login-language-switcher" />
      <div className="login-background-carousel" aria-hidden="true">
        {loginBackgrounds.map((background, index) => {
          const isActive = index === activeBackgroundIndex;
          const isOutgoing = index === outgoingBackgroundIndex;
          return (
            <div
              className={[
                "login-background-slide",
                isOutgoing ? "is-outgoing" : "",
                isActive ? "is-active" : "",
              ]
                .filter(Boolean)
                .join(" ")}
              data-active={isActive}
              data-outgoing={isOutgoing}
              key={background}
              style={{ backgroundImage: `url("${background}")` }}
            />
          );
        })}
      </div>
      <section
        className="login-hero-panel"
        aria-label={t("auth.platformOverview")}
      >
        <header className="login-brand-head">
          <span className="login-logo-frame">
            <img
              src={capfedLogoWhite}
              alt={`${primaryPlatformName} Logo`}
              width={48}
              height={48}
            />
          </span>
          <span className="login-brand-text">
            <strong>{platformShortName}</strong>
            <span>{secondaryPlatformName}</span>
          </span>
        </header>

        <div className="login-identity">
          <span className="login-mark">{t("auth.platformMark")}</span>
          <Typography.Title level={1}>{primaryPlatformName}</Typography.Title>
          <strong className="login-english-title">
            {secondaryPlatformName}
          </strong>
          <p className="login-institution">
            {locale === "en-US"
              ? teamInstitution.englishName
              : teamInstitution.name}
          </p>
          <div className="login-capability-tags">
            {capabilityTags.map((tag) => (
              <span key={tag}>{tag}</span>
            ))}
          </div>
        </div>

        <div className="login-stat-grid">
          {loginStats.map((stat) => (
            <BorderBeam color={oceanBorderBeam} key={stat.label}>
              <div className="login-stat">
                <span className="login-stat-icon">{stat.icon}</span>
                <strong>{stat.displayValue}</strong>
                <span>{stat.label}</span>
                <small>{stat.note}</small>
              </div>
            </BorderBeam>
          ))}
        </div>

        <BorderBeam color={oceanBorderBeam}>
          <div className="login-ops-panel">
            <div className="login-ops-copy">
              <span>
                {overview?.serviceStatus.title ?? t("auth.serviceStatus")}
              </span>
              <strong>
                {overview?.serviceStatus.headline ?? t("auth.loadingStatus")}
              </strong>
              <small>
                {overview?.serviceStatus.description ??
                  t("auth.statisticsUnavailable")}
              </small>
            </div>
            <div className="login-ops-status">
              <div className="login-station-grid" aria-hidden="true">
                {stationStatuses.map((station) => (
                  <i key={station.id} data-state={station.state} />
                ))}
              </div>
              <div className="login-status-legend">
                {serviceStatusSummary.map((item) => (
                  <span key={item.status}>
                    <i data-state={item.status} />
                    {item.label} {item.count}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </BorderBeam>

        <footer className="login-version-bar">
          <span>{overview?.platform.edition ?? platformEdition}</span>
          <span>{overview?.platform.version ?? platformVersion}</span>
          <span>
            {overview?.footer.statisticsNotice ?? t("auth.loadingStatistics")}
          </span>
        </footer>
      </section>

      <BorderBeam color={oceanBorderBeam}>
        <Card className="login-card" variant="borderless">
          <div className="login-card-header">
            <span className="login-card-logo">
              <img src={capfedLogoWhite} alt="" width={32} height={32} />
            </span>
            <span>
              <strong>{platformShortName}</strong>
              <small>{t("auth.unifiedAuthentication")}</small>
            </span>
          </div>
          <Typography.Title level={2}>
            {mode === "login" ? t("auth.login") : t("auth.register")}
          </Typography.Title>
          <Typography.Text type="secondary">
            {mode === "login"
              ? t("auth.loginSubtitle")
              : t("auth.registerSubtitle")}
          </Typography.Text>

          {mode === "login" ? (
            <Form<LoginFormValues>
              key="login"
              className="login-form"
              layout="vertical"
              initialValues={{ remember: true }}
              onFinish={handleFinish}
              requiredMark={false}
            >
              <Form.Item
                name="username"
                label={t("auth.username")}
                rules={[
                  { required: true, message: t("auth.requiredUsername") },
                ]}
              >
                <Input
                  prefix={<UserOutlined style={{ fontSize: 16 }} />}
                  placeholder={t("auth.usernamePlaceholder")}
                  autoComplete="username"
                  size="large"
                />
              </Form.Item>
              <Form.Item
                name="password"
                label={t("auth.password")}
                rules={[
                  { required: true, message: t("auth.requiredPassword") },
                ]}
              >
                <Input.Password
                  prefix={<LockOutlined style={{ fontSize: 16 }} />}
                  placeholder={t("auth.passwordPlaceholder")}
                  autoComplete="current-password"
                  size="large"
                />
              </Form.Item>
              <div className="login-options">
                <Form.Item name="remember" valuePropName="checked" noStyle>
                  <Checkbox>{t("auth.remember")}</Checkbox>
                </Form.Item>
                <Button
                  type="link"
                  size="small"
                  disabled={isSubmitting}
                  onClick={handleForgotPassword}
                >
                  {t("auth.forgotPassword")}
                </Button>
              </div>
              {!bootstrap.allowRegistration && (
                <Alert
                  type="info"
                  showIcon
                  title={t("auth.registrationClosed")}
                />
              )}
              <Button
                type="primary"
                htmlType="submit"
                block
                loading={submittingAction === "login"}
                disabled={isSubmitting && submittingAction !== "login"}
                icon={<LoginOutlined style={{ fontSize: 16 }} />}
                size="large"
              >
                {t("auth.loginButton")}
              </Button>
              <div
                className={
                  bootstrap.allowRegistration
                    ? "login-secondary-actions"
                    : "login-secondary-actions login-secondary-actions-single"
                }
              >
                <Button
                  type="link"
                  className="login-secondary-action"
                  loading={submittingAction === "guest"}
                  disabled={isSubmitting && submittingAction !== "guest"}
                  icon={<UserSwitchOutlined style={{ fontSize: 16 }} />}
                  onClick={handleGuestLogin}
                >
                  {t("auth.guestLogin")}
                </Button>
                {bootstrap.allowRegistration && (
                  <Button
                    type="link"
                    className="login-secondary-action"
                    disabled={isSubmitting}
                    icon={<UserAddOutlined style={{ fontSize: 16 }} />}
                    onClick={() => {
                      setAccountPurpose("standard");
                      setMode("register");
                    }}
                  >
                    {t("auth.registerNewAccount")}
                  </Button>
                )}
              </div>
              <div className="login-security-note">
                <SafetyCertificateOutlined style={{ fontSize: 16 }} />
                <span>{t("auth.permissionsAfterLogin")}</span>
              </div>
            </Form>
          ) : (
            <Form<RegisterFormValues>
              key="register"
              className="login-form"
              layout="vertical"
              initialValues={{ accountPurpose: "standard" }}
              onFinish={handleRegister}
              onFinishFailed={(errorInfo) => {
                message.error(
                  firstFormError(errorInfo, t("auth.checkRegistration")),
                );
              }}
              requiredMark={false}
            >
              <Form.Item
                name="username"
                label={t("auth.username")}
                rules={[
                  { required: true, message: t("auth.requiredUsername") },
                ]}
              >
                <Input
                  prefix={<UserOutlined style={{ fontSize: 16 }} />}
                  placeholder={t("auth.usernamePlaceholder")}
                  autoComplete="username"
                  size="large"
                />
              </Form.Item>
              <Form.Item
                name="email"
                label={t("auth.email")}
                rules={[
                  { required: true, message: t("auth.enterEmail") },
                  { type: "email", message: t("auth.validEmail") },
                ]}
              >
                <Input
                  placeholder={t("auth.enterEmail")}
                  autoComplete="email"
                  size="large"
                />
              </Form.Item>
              <Form.Item
                name="accountPurpose"
                label={t("auth.accountPurpose")}
                rules={[
                  { required: true, message: t("auth.selectAccountPurpose") },
                ]}
              >
                <Radio.Group
                  optionType="button"
                  buttonStyle="solid"
                  onChange={(event) => setAccountPurpose(event.target.value)}
                  options={[
                    { label: t("auth.standardUser"), value: "standard" },
                    { label: t("auth.researchUser"), value: "research" },
                  ]}
                />
              </Form.Item>
              {accountPurpose === "research" ? (
                <div className="login-research-fields">
                  <Form.Item
                    name="displayName"
                    label={t("auth.displayName")}
                    preserve={false}
                    rules={[{ required: true, message: t("auth.enterName") }]}
                  >
                    <Input
                      placeholder={t("auth.realNamePlaceholder")}
                      size="large"
                      maxLength={150}
                    />
                  </Form.Item>
                  <Form.Item
                    name="department"
                    label={t("auth.organization")}
                    preserve={false}
                    rules={[
                      { required: true, message: t("auth.enterOrganization") },
                    ]}
                  >
                    <Input
                      placeholder={t("auth.enterOrganization")}
                      size="large"
                      maxLength={120}
                    />
                  </Form.Item>
                  <Form.Item
                    name="applicationReason"
                    label={t("auth.applicationNote")}
                    preserve={false}
                    rules={[
                      {
                        required: true,
                        message: t("auth.enterApplicationNote"),
                      },
                    ]}
                  >
                    <Input.TextArea
                      placeholder={t("auth.applicationNotePlaceholder")}
                      autoSize={{ minRows: 2, maxRows: 3 }}
                      maxLength={500}
                      showCount
                    />
                  </Form.Item>
                </div>
              ) : null}
              <Alert
                type="info"
                showIcon
                title={
                  accountPurpose === "research"
                    ? t("auth.researchPending")
                    : t("auth.standardGranted")
                }
              />
              <Form.Item
                name="password"
                label={t("auth.password")}
                rules={[
                  { required: true, message: t("auth.requiredPassword") },
                  { min: 6, message: t("auth.passwordMin") },
                ]}
              >
                <Input.Password
                  prefix={<LockOutlined style={{ fontSize: 16 }} />}
                  placeholder={t("auth.passwordPlaceholder")}
                  autoComplete="new-password"
                  size="large"
                />
              </Form.Item>
              <Form.Item
                name="passwordConfirm"
                label={t("auth.confirmPassword")}
                dependencies={["password"]}
                rules={[
                  {
                    required: true,
                    message: t("auth.confirmPasswordPlaceholder"),
                  },
                  ({ getFieldValue }) => ({
                    validator(_, value) {
                      if (!value || getFieldValue("password") === value) {
                        return Promise.resolve();
                      }
                      return Promise.reject(
                        new Error(t("auth.passwordMismatch")),
                      );
                    },
                  }),
                ]}
              >
                <Input.Password
                  prefix={<LockOutlined style={{ fontSize: 16 }} />}
                  placeholder={t("auth.confirmPasswordPlaceholder")}
                  autoComplete="new-password"
                  size="large"
                />
              </Form.Item>
              <Button
                type="primary"
                htmlType="submit"
                block
                loading={submittingAction === "register"}
                disabled={isSubmitting && submittingAction !== "register"}
                icon={<LoginOutlined style={{ fontSize: 16 }} />}
                size="large"
              >
                {t("auth.registerButton")}
              </Button>
              <Button
                type="link"
                block
                disabled={isSubmitting}
                onClick={() => setMode("login")}
              >
                {t("auth.backToLogin")}
              </Button>
            </Form>
          )}
        </Card>
      </BorderBeam>
    </main>
  );
}

type FormValidationError = {
  errorFields: { errors: string[] }[];
};

function firstFormError(errorInfo: FormValidationError, fallback: string) {
  const firstError = errorInfo.errorFields[0]?.errors[0];
  return firstError || fallback;
}
