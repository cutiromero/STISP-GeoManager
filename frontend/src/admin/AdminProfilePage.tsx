import { LockOutlined, UploadOutlined, UserOutlined } from "@ant-design/icons";
import type { ProDescriptionsItemProps } from "@ant-design/pro-components";
import { ProCard, ProDescriptions } from "@ant-design/pro-components";
import {
  App,
  Avatar,
  Button,
  Drawer,
  Form,
  Input,
  Modal,
  Skeleton,
  Space,
  Tag,
  Typography,
  Upload,
} from "antd";
import type { Key } from "react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { useAppContext } from "../contexts/AppContext";
import type {
  AdminProfile,
  AdminProfilePasswordUpdate,
  AdminProfileUpdate,
} from "../types";
import { PermissionPanel } from "./PermissionPanel";

interface ProfileDescriptionItem {
  username: string;
  displayName: string;
  roles: string[];
  department: string;
  email: string;
}

function createProfileDescriptionColumns(
  onManagePermissions: () => void,
  onChangePassword: () => void,
  english = false,
): ProDescriptionsItemProps<ProfileDescriptionItem>[] {
  return [
    {
      title: english ? "Username" : "用户名",
      dataIndex: "username",
      tooltip: english
        ? "The username is fixed when the account is created"
        : "用户名在创建时确定，不可修改",
      editable: false,
    },
    {
      title: english ? "Display name" : "显示名称",
      dataIndex: "displayName",
    },
    {
      title: english ? "Email" : "邮箱",
      dataIndex: "email",
      copyable: true,
      formItemProps: {
        rules: [
          {
            required: true,
            message: english ? "Enter an email address" : "请输入邮箱",
          },
          {
            type: "email",
            message: english ? "Enter a valid email address" : "请输入有效邮箱",
          },
        ],
      },
    },
    {
      title: english ? "Roles" : "角色",
      dataIndex: "roles",
      editable: false,
      render: (_, entity) =>
        entity.roles && entity.roles.length > 0 ? (
          <Space size={[8, 8]} wrap>
            {entity.roles.map((role) => (
              <Tag key={role} color="blue">
                {role}
              </Tag>
            ))}
          </Space>
        ) : (
          <Typography.Text type="secondary">
            {english ? "No roles assigned" : "未分配角色"}
          </Typography.Text>
        ),
    },
    {
      title: english ? "Department" : "部门",
      dataIndex: "department",
    },
    {
      title: english ? "My permissions" : "我的权限",
      key: "permissions",
      editable: false,
      render: () => (
        <Typography.Link onClick={onManagePermissions}>
          {english ? "Manage permissions" : "管理权限"}
        </Typography.Link>
      ),
    },
    {
      title: english ? "Change password" : "更改密码",
      key: "password",
      editable: false,
      render: () => (
        <Typography.Link onClick={onChangePassword}>
          {english ? "Change password" : "修改密码"}
        </Typography.Link>
      ),
    },
  ];
}

function getCookie(name: string): string | null {
  const match = document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null;
}

export default function AdminProfilePage() {
  const { message } = App.useApp();
  const { i18n } = useTranslation();
  const english =
    i18n.resolvedLanguage?.toLowerCase().startsWith("en") ?? false;
  const { setUser } = useAppContext();
  const [passwordForm] = Form.useForm<AdminProfilePasswordUpdate>();
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [avatarUploading, setAvatarUploading] = useState(false);
  const [avatarVersion, setAvatarVersion] = useState(0);
  const [permDrawerOpen, setPermDrawerOpen] = useState(false);
  const [passwordModalOpen, setPasswordModalOpen] = useState(false);

  useEffect(() => {
    let mounted = true;
    async function loadProfile() {
      try {
        const data = await api.adminProfile();
        if (!mounted) return;
        setProfile(data);
      } catch (error) {
        message.error(
          error instanceof Error
            ? error.message
            : english
              ? "Failed to load user profile"
              : "用户资料加载失败",
        );
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    }
    loadProfile();
    return () => {
      mounted = false;
    };
  }, [english, message]);

  async function handleProfileSave(values: AdminProfileUpdate) {
    const updated = await api.updateAdminProfile(values);
    setProfile(updated);
    setUser(updated.user);
    message.success(english ? "Profile saved" : "个人信息已保存");
    return true;
  }

  async function handleProfileDescriptionSave(
    _key: Key | Key[],
    values: ProfileDescriptionItem,
  ) {
    await handleProfileSave({
      ...values,
      avatarUrl: profile?.avatarUrl ?? "",
    });
  }

  async function handlePermissionChange(
    permissionId: string,
    enabled: boolean,
  ) {
    if (!profile) return;
    const disabledPermissions = new Set(profile.disabledPermissions);
    if (enabled) {
      disabledPermissions.delete(permissionId);
    } else {
      disabledPermissions.add(permissionId);
    }
    try {
      const updated = await api.updateAdminProfilePermissions({
        disabledPermissions: [...disabledPermissions],
      });
      setProfile(updated);
      setUser(updated.user);
      message.success(
        english ? "Permission preferences updated" : "权限偏好已更新",
      );
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : english
            ? "Failed to update permission preferences"
            : "权限偏好更新失败",
      );
    }
  }

  async function handlePasswordSave(values: AdminProfilePasswordUpdate) {
    try {
      await api.updateAdminProfilePassword(values);
      passwordForm.resetFields();
      setPasswordModalOpen(false);
      message.success(english ? "Password updated" : "密码已更新");
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : english
            ? "Failed to update password"
            : "密码更新失败",
      );
    }
  }

  // oxlint-disable-next-line typescript/no-explicit-any -- antd Upload customRequest type
  const handleAvatarUpload = async (options: any) => {
    const { file, onSuccess, onError } = options;
    setAvatarUploading(true);

    try {
      const formData = new FormData();
      formData.append("avatar", file);

      const response = await fetch("/api/admin/profile/avatar/", {
        method: "POST",
        credentials: "include",
        headers: {
          "X-CSRFToken": getCookie("csrftoken") ?? "",
        },
        body: formData,
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(
          error.detail || (english ? "Upload failed" : "上传失败"),
        );
      }

      const updated = await response.json();
      setProfile(updated);
      setUser(updated.user);
      onSuccess?.(updated);
      setAvatarVersion((v) => v + 1);
      message.success(english ? "Avatar uploaded" : "头像上传成功");
    } catch (error) {
      onError?.(error as Error);
      message.error(
        error instanceof Error
          ? error.message
          : english
            ? "Failed to upload avatar"
            : "头像上传失败",
      );
    } finally {
      setAvatarUploading(false);
    }
  };

  if (loading) {
    return (
      <ProCard className="admin-section-card">
        <Skeleton active paragraph={{ rows: 8 }} />
      </ProCard>
    );
  }

  const grantedPermissions = profile?.grantedPermissions ?? [];
  const disabledPermissions = profile?.disabledPermissions ?? [];
  const profileDescriptionData: ProfileDescriptionItem = {
    username: profile?.user.username ?? "",
    displayName: profile?.user.displayName ?? "",
    roles: profile?.user.roles ?? [],
    email: profile?.user.email ?? "",
    department: profile?.department ?? "",
  };
  const profileDescriptionColumns = createProfileDescriptionColumns(
    () => setPermDrawerOpen(true),
    () => setPasswordModalOpen(true),
    english,
  );

  return (
    <div className="admin-page-stack">
      <ProCard
        title={english ? "Profile" : "个人信息"}
        className="admin-section-card"
      >
        <div className="admin-profile-shell">
          <Upload
            name="avatar"
            showUploadList={false}
            customRequest={handleAvatarUpload}
            beforeUpload={(file) => {
              const isJpgOrPng =
                file.type === "image/jpeg" || file.type === "image/png";
              if (!isJpgOrPng) {
                message.error(
                  english
                    ? "Only JPG and PNG images are supported"
                    : "仅支持 JPG/PNG 格式的图片",
                );
              }
              const isLt2M = file.size / 1024 / 1024 < 2;
              if (!isLt2M) {
                message.error(
                  english
                    ? "Image size cannot exceed 2 MB"
                    : "图片大小不能超过 2 MB",
                );
              }
              return isJpgOrPng && isLt2M;
            }}
            disabled={avatarUploading}
          >
            <div className="admin-avatar-wrapper admin-avatar-editable">
              <Avatar
                size={88}
                src={avatarSrc(profile?.avatarUrl, avatarVersion)}
                icon={<UserOutlined />}
              />
              <div className="admin-avatar-overlay">
                <UploadOutlined />
                <span>
                  {avatarUploading
                    ? english
                      ? "Uploading..."
                      : "上传中..."
                    : english
                      ? "Change avatar"
                      : "更换头像"}
                </span>
              </div>
            </div>
          </Upload>
          <ProDescriptions<ProfileDescriptionItem>
            className="admin-profile-descriptions"
            column={3}
            columns={profileDescriptionColumns}
            dataSource={profileDescriptionData}
            editable={{
              onSave: handleProfileDescriptionSave,
            }}
            emptyText={english ? "Not provided" : "未填写"}
          />
        </div>
      </ProCard>

      <Modal
        title={english ? "Change password" : "修改密码"}
        open={passwordModalOpen}
        footer={null}
        onCancel={() => setPasswordModalOpen(false)}
        afterClose={() => passwordForm.resetFields()}
        destroyOnHidden
      >
        <Form
          form={passwordForm}
          layout="vertical"
          className="admin-password-form"
          onFinish={handlePasswordSave}
          onFinishFailed={(errorInfo) => {
            message.error(
              firstFormError(
                errorInfo,
                english ? "Check the password fields" : "请检查密码信息",
              ),
            );
          }}
        >
          <Form.Item
            name="currentPassword"
            label={english ? "Current password" : "当前密码"}
            rules={[
              {
                required: true,
                message: english
                  ? "Enter the current password"
                  : "请输入当前密码",
              },
            ]}
          >
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Form.Item
            name="newPassword"
            label={english ? "New password" : "新密码"}
            rules={[
              {
                required: true,
                message: english ? "Enter a new password" : "请输入新密码",
              },
              {
                validator: (_, value: string | undefined) => {
                  const password = value ?? "";
                  if (!password) return Promise.resolve();
                  if (password.length < 6) {
                    return Promise.reject(
                      new Error(
                        english
                          ? "Password must contain at least 6 characters"
                          : "密码长度至少 6 位",
                      ),
                    );
                  }
                  if (password.length > 16) {
                    return Promise.reject(
                      new Error(
                        english
                          ? "Password cannot exceed 16 characters"
                          : "密码长度不能超过 16 位",
                      ),
                    );
                  }
                  return Promise.resolve();
                },
              },
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            name="passwordConfirm"
            label={english ? "Confirm new password" : "确认新密码"}
            dependencies={["newPassword"]}
            rules={[
              {
                required: true,
                message: english
                  ? "Enter the new password again"
                  : "请再次输入新密码",
              },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue("newPassword") === value) {
                    return Promise.resolve();
                  }
                  return Promise.reject(
                    new Error(
                      english
                        ? "The new passwords do not match"
                        : "两次输入的新密码不一致",
                    ),
                  );
                },
              }),
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" icon={<LockOutlined />}>
            {english ? "Update password" : "更新密码"}
          </Button>
        </Form>
      </Modal>

      <Drawer
        title={english ? "My permissions" : "我的权限"}
        open={permDrawerOpen}
        onClose={() => setPermDrawerOpen(false)}
        size="large"
      >
        <PermissionPanel
          mode="profile"
          availablePermissions={profile?.availablePermissions ?? []}
          grantedPermissions={grantedPermissions}
          disabledPermissions={disabledPermissions}
          onChange={handlePermissionChange}
        />
      </Drawer>
    </div>
  );
}

type FormValidationError = {
  errorFields: { errors: string[] }[];
};

function firstFormError(errorInfo: FormValidationError, fallback: string) {
  const firstError = errorInfo.errorFields[0]?.errors[0];
  return firstError || fallback;
}

function avatarSrc(
  url: string | undefined,
  version: number,
): string | undefined {
  if (!url) return undefined;
  if (version > 0 && url.startsWith("/")) {
    return `${url}?v=${version}`;
  }
  return url;
}
