import {
  LockOutlined,
  LoginOutlined,
  SafetyCertificateOutlined,
  UserAddOutlined,
  UserOutlined,
  UserSwitchOutlined,
} from "@ant-design/icons";
import { Alert, App, Button, Card, Form, Input, Radio, Typography } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import stispLogoWhite from "../assets/stisp-logo-white.svg";
import { teamInstitution } from "../about/institution";
import LanguageSwitcher from "../components/LanguageSwitcher";
import { platformBrand } from "../config/platformBrand";
import { useAppContext } from "../contexts/AppContext";
import { currentLocale } from "../i18n";
import type { LoginFormValues, RegisterFormValues } from "../types";
import LoginBackground from "./LoginBackground";

const platformChineseName = platformBrand.chineseName;
const platformEnglishName = platformBrand.englishName;
const platformShortName = platformBrand.shortName;
const platformEdition = platformBrand.edition;
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
  const isSubmitting = submittingAction !== null;
  const primaryPlatformName =
    locale === "en-US" ? platformEnglishName : platformChineseName;
  const secondaryPlatformName =
    locale === "en-US" ? platformChineseName : platformEnglishName;
  async function handleFinish(values: LoginFormValues) {
    setSubmittingAction("login");
    try {
      await api.csrf();
      const response = await api.login(values.username, values.password, false);
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
      <LoginBackground />
      <section
        className="login-hero-panel"
        aria-label={t("auth.platformOverview")}
      >
        <header className="login-brand-head">
          <span className="login-logo-frame">
            <img
              src={stispLogoWhite}
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
          <p className="login-platform-description">
            {t("auth.platformDescription")}
          </p>
        </div>

        <footer className="login-version-bar">
          <span>{platformEdition}</span>
        </footer>
      </section>

      <Card className="login-card" variant="borderless">
        <div className="login-card-header">
          <span className="login-card-logo">
            <img src={stispLogoWhite} alt="" width={32} height={32} />
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
            onFinish={handleFinish}
            requiredMark={false}
          >
            <Form.Item
              name="username"
              label={t("auth.username")}
              rules={[{ required: true, message: t("auth.requiredUsername") }]}
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
              rules={[{ required: true, message: t("auth.requiredPassword") }]}
            >
              <Input.Password
                prefix={<LockOutlined style={{ fontSize: 16 }} />}
                placeholder={t("auth.passwordPlaceholder")}
                autoComplete="current-password"
                size="large"
              />
            </Form.Item>
            <div className="login-options">
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
              rules={[{ required: true, message: t("auth.requiredUsername") }]}
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
