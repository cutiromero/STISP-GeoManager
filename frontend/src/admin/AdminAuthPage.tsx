import {
  CheckOutlined,
  CloseOutlined,
  DeleteOutlined,
  EllipsisOutlined,
  EyeOutlined,
  KeyOutlined,
  PlusOutlined,
  SafetyCertificateOutlined,
  StopOutlined,
  TeamOutlined,
  UserOutlined,
} from "@ant-design/icons";
import type { ProColumns } from "@ant-design/pro-components";
import { ProTable } from "@ant-design/pro-components";
import type { MenuProps } from "antd";
import {
  Alert,
  App,
  Avatar,
  Button,
  Drawer,
  Dropdown,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Result,
  Select,
  Space,
  Spin,
  Switch,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { api } from "../api/client";
import { useAppContext } from "../contexts/AppContext";
import { localText, useEnglishLanguage } from "../i18n/useEnglishLanguage";
import type {
  AdminOperationLog,
  AdminPermissionItem,
  Group,
  RoleApplicationListItem,
  User,
} from "../types";
import { PermissionPanel } from "./PermissionPanel";
import { UserSummaryCards } from "./UserSummaryCards";

const operationResultText: Record<string, string> = {
  success: "成功",
  warning: "告警",
  failed: "失败",
};

const operationResultTextEnglish: Record<string, string> = {
  success: "Success",
  warning: "Warning",
  failed: "Failed",
};

const operationResultColor: Record<string, string> = {
  success: "success",
  warning: "warning",
  failed: "error",
};

const builtinRoleInfo: Record<
  string,
  { color: string; tag: string; summary: string }
> = {
  超级管理员: {
    color: "volcano",
    tag: "全量锁定",
    summary: "拥有全部权限，含数据备份和系统根权限。",
  },
  平台管理员: {
    color: "blue",
    tag: "数据运维",
    summary: "管理用户、角色、业务日志和全部数据，不开放底层系统维护能力。",
  },
  科研用户: {
    color: "green",
    tag: "高级数据",
    summary: "可上传、浏览、查询、加载、导出，并使用符号化和 AI 解译。",
  },
  普通用户: {
    color: "cyan",
    tag: "基础数据",
    summary: "可浏览、查询和加载授权范围内的数据与共享成果。",
  },
  游客: {
    color: "default",
    tag: "公开浏览",
    summary: "仅可浏览、查询和加载明确公开共享的数据与成果。",
  },
};

const builtinRoleOrder = [
  "超级管理员",
  "平台管理员",
  "科研用户",
  "普通用户",
  "游客",
];

const builtinRoleInfoEnglish: Record<
  string,
  { name: string; tag: string; summary: string }
> = {
  超级管理员: {
    name: "Super Administrator",
    tag: "Fully locked",
    summary:
      "Full platform control, including backups and system-level permissions.",
  },
  平台管理员: {
    name: "Platform Administrator",
    tag: "Data operations",
    summary:
      "Manages users, roles, business logs, and all data without system-root maintenance access.",
  },
  科研用户: {
    name: "Research User",
    tag: "Advanced data",
    summary:
      "Can upload, browse, query, load, export, symbolize, and use AI interpretation tools.",
  },
  普通用户: {
    name: "Standard User",
    tag: "Basic data",
    summary: "Can browse, query, and load authorized data and shared results.",
  },
  游客: {
    name: "Guest",
    tag: "Public browsing",
    summary:
      "Can browse, query, and load explicitly public data and results only.",
  },
};

export default function AdminAuthPage() {
  const { message, modal } = App.useApp();
  const english = useEnglishLanguage();
  const l = (zh: string, en: string) => localText(english, zh, en);
  const { user } = useAppContext();
  const location = useLocation();
  const activeSection = location.pathname.endsWith("/groups")
    ? "groups"
    : "users";
  const canManageAuth = Boolean(user?.permissions.canManageAuth);
  const canCreateUser = Boolean(user?.permissions.canCreateUser);
  const canManagePermissions = Boolean(
    user?.permissions.canManageFeaturePermissions,
  );
  const isSuperadmin = Boolean(user?.roles.includes("超级管理员"));
  const [createGroupForm] = Form.useForm<{ name: string }>();
  const [createUserForm] = Form.useForm<{
    username: string;
    password: string;
    displayName?: string;
    email?: string;
    department?: string;
    groupIds?: number[];
    isActive?: boolean;
  }>();
  const [users, setUsers] = useState<User[]>([]);
  const [roleApplications, setRoleApplications] = useState<
    RoleApplicationListItem[]
  >([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [availablePermissions, setAvailablePermissions] = useState<
    AdminPermissionItem[]
  >([]);
  const [loading, setLoading] = useState(true);
  const [activeUser, setActiveUser] = useState<User | null>(null);
  const [logUser, setLogUser] = useState<User | null>(null);
  const [groupUser, setGroupUser] = useState<User | null>(null);
  const [permissionUser, setPermissionUser] = useState<User | null>(null);
  const [selectedGroupIds, setSelectedGroupIds] = useState<number[]>([]);
  const [createGroupOpen, setCreateGroupOpen] = useState(false);
  const [createUserOpen, setCreateUserOpen] = useState(false);
  const [groupDrafts, setGroupDrafts] = useState<Record<number, string[]>>({});
  const [userPermissionDrafts, setUserPermissionDrafts] = useState<
    Record<number, string[]>
  >({});
  const [userDisabledPermissionDrafts, setUserDisabledPermissionDrafts] =
    useState<Record<number, string[]>>({});
  const [userLogGroupDrafts, setUserLogGroupDrafts] = useState<
    Record<number, number[]>
  >({});
  const [permissionGroup, setPermissionGroup] = useState<Group | null>(null);

  const loadAuthData = useCallback(async () => {
    if (!canManageAuth) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const [userData, groupData, roleApplicationData] = await Promise.all([
        api.adminUsers(),
        api.adminGroups(),
        api.roleApplications(),
      ]);
      setUsers(userData.items);
      setGroups(groupData.items);
      setRoleApplications(roleApplicationData.items);
      setAvailablePermissions(groupData.availablePermissions);
      setGroupDrafts(
        Object.fromEntries(
          groupData.items.map((group) => [group.id, group.permissions]),
        ),
      );
      setUserPermissionDrafts(
        Object.fromEntries(
          userData.items.map((item) => [item.id, item.directPermissions ?? []]),
        ),
      );
      setUserDisabledPermissionDrafts(
        Object.fromEntries(
          userData.items.map((item) => [
            item.id,
            item.disabledPermissions ?? [],
          ]),
        ),
      );
      setUserLogGroupDrafts(
        Object.fromEntries(
          userData.items.map((item) => [
            item.id,
            item.operationLogGroupIds ?? [],
          ]),
        ),
      );
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : l(
              "认证授权数据加载失败",
              "Failed to load authentication and authorization data",
            ),
      );
    } finally {
      setLoading(false);
    }
  }, [canManageAuth, english, message]);

  useEffect(() => {
    loadAuthData();
  }, [loadAuthData]);

  const groupNameById = useMemo(
    () =>
      new Map(
        groups.map((group) => [
          group.id,
          builtinRoleDisplayName(group.name, english),
        ]),
      ),
    [english, groups],
  );
  const guestRoleId = useMemo(
    () => groups.find(isGuestRole)?.id ?? null,
    [groups],
  );
  const groupOptions = useMemo(
    () =>
      groups.map((group) => {
        const guestRole = isGuestRole(group);
        return {
          label: guestRole
            ? l(
                `${group.name}（系统专用）`,
                `${builtinRoleDisplayName(group.name, true)} (system only)`,
              )
            : builtinRoleDisplayName(group.name, english),
          value: group.id,
          disabled:
            guestRole ||
            isGroupMembershipLocked(group) ||
            (group.name === "平台管理员" && !isSuperadmin),
        };
      }),
    [english, groups, isSuperadmin],
  );
  const sortedUsers = useMemo(() => {
    if (!user) return users;
    return [
      ...users.filter((item) => item.id === user.id),
      ...users.filter((item) => item.id !== user.id),
    ];
  }, [user, users]);
  const permissionLabelById = useMemo(
    () =>
      new Map(
        availablePermissions.map((permission) => [
          permission.id,
          permission.label,
        ]),
      ),
    [availablePermissions],
  );

  const userColumns: ProColumns<User>[] = [
    {
      title: l("账号", "Account"),
      dataIndex: "username",
      width: 180,
      render: (_, record) => (
        <UserIdentity
          user={record}
          title={
            <Button
              className="admin-user-link"
              type="link"
              onClick={() => setActiveUser(record)}
            >
              {record.username}
            </Button>
          }
          description={
            record.displayName || l("未设置显示名", "No display name")
          }
        />
      ),
    },
    {
      title: l("联系信息", "Contact"),
      dataIndex: "email",
      width: 220,
      render: (_, record) => (
        <Space orientation="vertical" size={0}>
          <Typography.Text ellipsis>
            {record.email || l("未设置邮箱", "No email")}
          </Typography.Text>
          <Typography.Text type="secondary" ellipsis>
            {record.department || l("未设置部门", "No department")}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: l("角色", "Roles"),
      dataIndex: "groupIds",
      width: 210,
      search: false,
      render: (_, record) => (
        <GroupTags
          groupIds={record.groupIds}
          groupNameById={groupNameById}
          maxVisible={2}
        />
      ),
    },
    {
      title: l("状态", "Status"),
      dataIndex: "isActive",
      valueType: "select",
      width: 88,
      valueEnum: {
        true: { text: l("启用", "Enabled"), status: "Success" },
        false: { text: l("停用", "Disabled"), status: "Error" },
      },
      render: (_, record) =>
        record.isActive ? (
          <Tag color="success">{l("启用", "Enabled")}</Tag>
        ) : (
          <Tag color="error">{l("停用", "Disabled")}</Tag>
        ),
    },
    {
      title: l("操作", "Actions"),
      valueType: "option",
      width: 120,
      render: (_, record) => [
        <Button
          key="detail"
          type="link"
          icon={<EyeOutlined />}
          onClick={() => setLogUser(record)}
        >
          {l("查看", "View")}
        </Button>,
        <Dropdown
          key="actions"
          trigger={["click"]}
          menu={{
            items: userActionItems(record),
            onClick: ({ key }) => handleUserAction(key, record),
          }}
        >
          <Button type="link" icon={<EllipsisOutlined />}>
            {l("操作", "Actions")}
          </Button>
        </Dropdown>,
      ],
    },
  ];

  const userLogColumns: ProColumns<AdminOperationLog>[] = [
    {
      title: l("操作时间", "Time"),
      dataIndex: "occurredAt",
      width: 180,
      render: (_, record) => record.occurredAt,
    },
    {
      title: l("模块", "Module"),
      dataIndex: "module",
      width: 120,
      ellipsis: true,
    },
    {
      title: l("动作", "Action"),
      dataIndex: "action",
      width: 140,
      ellipsis: true,
    },
    {
      title: l("结果", "Result"),
      dataIndex: "result",
      width: 88,
      render: (_, record) => (
        <Tag color={operationResultColor[record.result] ?? "default"}>
          {(english ? operationResultTextEnglish : operationResultText)[
            record.result
          ] ?? record.result}
        </Tag>
      ),
    },
    {
      title: l("摘要", "Summary"),
      dataIndex: "summary",
      width: 280,
      ellipsis: true,
    },
  ];

  const roleApplicationColumns: ProColumns<RoleApplicationListItem>[] = [
    {
      title: l("申请用户", "Applicant"),
      dataIndex: ["user", "username"],
      width: 190,
      render: (_, record) => (
        <Space orientation="vertical" size={0}>
          <Typography.Text strong>
            {record.user.displayName || record.user.username}
          </Typography.Text>
          <Typography.Text type="secondary">
            {record.user.username}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: l("联系信息", "Contact"),
      dataIndex: ["user", "email"],
      width: 230,
      render: (_, record) => (
        <Space orientation="vertical" size={0}>
          <Typography.Text>{record.user.email}</Typography.Text>
          <Typography.Text type="secondary">
            {record.user.department}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: l("申请说明", "Application reason"),
      dataIndex: "reason",
      width: 300,
      ellipsis: true,
    },
    {
      title: l("状态", "Status"),
      dataIndex: "status",
      width: 100,
      render: (_, record) => {
        const statusMeta = (
          {
            pending: { color: "processing", label: l("待审核", "Pending") },
            approved: { color: "success", label: l("已通过", "Approved") },
            rejected: { color: "error", label: l("已拒绝", "Rejected") },
          } satisfies Record<
            RoleApplicationListItem["status"],
            { color: string; label: string }
          >
        )[record.status];
        return <Tag color={statusMeta.color}>{statusMeta.label}</Tag>;
      },
    },
    {
      title: l("申请时间", "Applied at"),
      dataIndex: "createdAt",
      width: 180,
      render: (_, record) =>
        new Date(record.createdAt).toLocaleString(english ? "en-US" : "zh-CN"),
    },
    {
      title: l("操作", "Actions"),
      valueType: "option",
      width: 160,
      render: (_, record) =>
        record.status === "pending"
          ? [
              <Button
                key="approve"
                type="link"
                icon={<CheckOutlined />}
                onClick={() => handleRoleApplicationReview(record, "approve")}
              >
                {l("通过", "Approve")}
              </Button>,
              <Button
                key="reject"
                type="link"
                danger
                icon={<CloseOutlined />}
                onClick={() => handleRoleApplicationReview(record, "reject")}
              >
                {l("拒绝", "Reject")}
              </Button>,
            ]
          : [
              <Typography.Text key="reviewer" type="secondary">
                {record.reviewer?.displayName || l("已审核", "Reviewed")}
              </Typography.Text>,
            ],
    },
  ];

  const groupColumns: ProColumns<Group>[] = [
    {
      title: l("角色", "Role"),
      dataIndex: "name",
      width: "24%",
      render: (_, record) => {
        const roleInfo = builtinRoleInfo[record.name];
        const englishRoleInfo = builtinRoleInfoEnglish[record.name];
        return (
          <Space orientation="vertical" size={2}>
            <Space size={6} wrap>
              <Typography.Text strong>
                {builtinRoleDisplayName(record.name, english)}
              </Typography.Text>
              {roleInfo ? (
                <Tag color={roleInfo.color}>
                  {english ? englishRoleInfo?.tag : roleInfo.tag}
                </Tag>
              ) : null}
            </Space>
            {roleInfo ? (
              <Typography.Text type="secondary">
                {english ? englishRoleInfo?.summary : roleInfo.summary}
              </Typography.Text>
            ) : null}
            <Space size={[6, 6]} wrap>
              <Tag color="blue">
                {l(`${record.userCount} 人`, `${record.userCount} users`)}
              </Tag>
              {record.isProtected ? (
                <Tag color="geekblue">{l("内置", "Built in")}</Tag>
              ) : null}
              {record.lockedPermissions.length > 0 ? (
                <Tag color="volcano">{l("权限锁定", "Permissions locked")}</Tag>
              ) : null}
            </Space>
          </Space>
        );
      },
    },
    {
      title: l("已授予权限", "Granted permissions"),
      dataIndex: "permissions",
      width: "56%",
      search: false,
      render: (_, record) =>
        record.permissions.length > 0 ? (
          <PermissionTags
            permissionIds={record.permissions}
            permissionLabelById={permissionLabelById}
            maxVisible={6}
          />
        ) : (
          <Typography.Text type="secondary">
            {l("暂未授予功能权限", "No feature permissions granted")}
          </Typography.Text>
        ),
    },
    {
      title: l("操作", "Actions"),
      valueType: "option",
      width: "20%",
      render: (_, record) => [
        <Button
          key="permissions"
          type="link"
          icon={<EyeOutlined />}
          disabled={!canEditGroupPermissions(record)}
          onClick={() => openPermissionDrawer(record)}
        >
          {l("权限", "Permissions")}
        </Button>,
        record.userCount === 0 && !record.isProtected ? (
          <Popconfirm
            key="delete"
            title={l("确认删除空角色？", "Delete this empty role?")}
            description={l(
              "删除前请确认该角色没有关联用户。",
              "Confirm that the role has no associated users before deleting it.",
            )}
            onConfirm={() => handleDeleteGroup(record)}
          >
            <Button type="link" danger icon={<DeleteOutlined />}>
              {l("删除", "Delete")}
            </Button>
          </Popconfirm>
        ) : (
          <Button
            key="delete"
            type="link"
            danger
            icon={<DeleteOutlined />}
            disabled
          >
            {l("删除", "Delete")}
          </Button>
        ),
      ],
    },
  ];

  const userStats = useMemo(
    () => ({
      active: users.filter((user) => user.isActive).length,
      disabled: users.filter((user) => !user.isActive).length,
      groups: groups.length,
    }),
    [groups.length, users],
  );

  async function handleCreateGroup() {
    if (!canManagePermissions) return;
    try {
      const values = await createGroupForm.validateFields();
      const group = await api.createAdminGroup({
        name: values.name,
        permissions: [],
      });
      setGroups((current) => [...current, group]);
      setGroupDrafts((current) => ({
        ...current,
        [group.id]: group.permissions,
      }));
      createGroupForm.resetFields();
      setCreateGroupOpen(false);
      message.success(l("角色已创建", "Role created"));
    } catch (error) {
      message.error(
        formOrApiError(error, l("角色创建失败", "Failed to create role")),
      );
    }
  }

  async function handleCreateUser() {
    if (!canCreateUser) return;
    try {
      const values = await createUserForm.validateFields();
      if (guestRoleId && values.groupIds?.includes(guestRoleId)) {
        message.error(
          l(
            "游客角色仅供系统 guest 账号使用，不能分配给其他账号",
            "The guest role is reserved for the system guest account and cannot be assigned to other accounts",
          ),
        );
        return;
      }
      const result = await api.createAdminUser({
        username: values.username,
        displayName: values.displayName ?? "",
        email: values.email ?? "",
        department: values.department ?? "",
        groupIds: values.groupIds as [number, ...number[]],
        isActive: values.isActive ?? true,
      });
      createUserForm.resetFields();
      setCreateUserOpen(false);
      if (result.generatedPassword) {
        showGeneratedPasswordModal({
          title: l("用户创建成功", "User created"),
          username: result.username,
          password: result.generatedPassword,
        });
      } else {
        message.success(l("用户已创建", "User created"));
      }
      await loadAuthData();
    } catch (error) {
      message.error(
        formOrApiError(error, l("用户创建失败", "Failed to create user")),
      );
    }
  }

  function openUserGroupDrawer(targetUser: User) {
    if (
      targetUser.id === user?.id ||
      hasLockedGroupMembership(targetUser, groups)
    ) {
      return;
    }
    setGroupUser(targetUser);
    setSelectedGroupIds(targetUser.groupIds);
  }

  function openUserPermissionDrawer(targetUser: User) {
    if (targetUser.id === user?.id) {
      return;
    }
    setUserPermissionDrafts((current) => ({
      ...current,
      [targetUser.id]:
        current[targetUser.id] ?? targetUser.directPermissions ?? [],
    }));
    setUserDisabledPermissionDrafts((current) => ({
      ...current,
      [targetUser.id]:
        current[targetUser.id] ?? targetUser.disabledPermissions ?? [],
    }));
    setUserLogGroupDrafts((current) => ({
      ...current,
      [targetUser.id]:
        current[targetUser.id] ?? targetUser.operationLogGroupIds ?? [],
    }));
    setPermissionUser(targetUser);
  }

  function userActionItems(record: User): MenuProps["items"] {
    const cannotEditOwnGroups = record.id === user?.id;
    const cannotEditLockedGroups = hasLockedGroupMembership(record, groups);
    const cannotEditGuest = isGuestAccount(record);
    const groupDisabledReason = cannotEditOwnGroups
      ? l("不能修改自己的角色", "You cannot change your own roles")
      : cannotEditLockedGroups
        ? l("不能修改系统锁定角色", "System-locked roles cannot be changed")
        : cannotEditGuest
          ? l(
              "游客账号不能修改角色",
              "The guest account's role cannot be changed",
            )
          : "";
    const cannotEditOwnPermissions = record.id === user?.id;
    return [
      {
        key: "groups",
        icon: <TeamOutlined />,
        label: groupDisabledReason ? (
          <Tooltip title={groupDisabledReason}>
            <span title={groupDisabledReason}>
              {l("更改角色", "Change roles")}
            </span>
          </Tooltip>
        ) : (
          l("更改角色", "Change roles")
        ),
        disabled: Boolean(groupDisabledReason),
      },
      {
        key: "permissions",
        icon: <SafetyCertificateOutlined />,
        label: cannotEditOwnPermissions ? (
          <Tooltip
            title={l(
              "请到用户设置中修改自己的权限",
              "Change your own permissions in User Settings",
            )}
          >
            <span
              title={l(
                "请到用户设置中修改自己的权限",
                "Change your own permissions in User Settings",
              )}
            >
              {l("更改权限", "Change permissions")}
            </span>
          </Tooltip>
        ) : (
          l("更改权限", "Change permissions")
        ),
        disabled:
          !canManagePermissions || cannotEditOwnPermissions || cannotEditGuest,
      },
      {
        key: "status",
        icon: <StopOutlined />,
        label: record.isActive ? l("停用", "Disable") : l("启用", "Enable"),
        disabled: record.id === user?.id || cannotEditGuest,
      },
      {
        key: "resetPassword",
        icon: <KeyOutlined />,
        label: l("重置密码", "Reset password"),
        disabled: record.id === user?.id || cannotEditGuest,
      },
      {
        key: "delete",
        icon: <DeleteOutlined />,
        label: l("删除", "Delete"),
        danger: true,
        disabled: record.id === user?.id || cannotEditGuest,
      },
    ];
  }

  function handleUserAction(key: string, targetUser: User) {
    if (key === "groups") {
      openUserGroupDrawer(targetUser);
      return;
    }
    if (key === "permissions") {
      openUserPermissionDrawer(targetUser);
      return;
    }
    if (key === "status") {
      handleToggleUserStatus(targetUser);
      return;
    }
    if (key === "resetPassword") {
      handleResetUserPassword(targetUser);
      return;
    }
    if (key === "delete") {
      handleDeleteUser(targetUser);
    }
  }

  function showGeneratedPasswordModal({
    title,
    username,
    password,
  }: {
    title: string;
    username: string;
    password: string;
  }) {
    Modal.success({
      title,
      content: (
        <div>
          <p>
            {l("用户", "The password for user")} <strong>{username}</strong>{" "}
            {l("的密码已生成。", "has been generated.")}
          </p>
          <p>
            {l("新密码：", "New password: ")}
            <Typography.Text copyable>{password}</Typography.Text>
          </p>
          <p>
            {l(
              "请妥善保存此密码，关闭后将无法再次查看。",
              "Store this password securely. It cannot be viewed again after this dialog is closed.",
            )}
          </p>
        </div>
      ),
    });
  }

  function handleToggleUserStatus(targetUser: User) {
    const nextActive = !targetUser.isActive;
    modal.confirm({
      title: nextActive
        ? l("确认启用用户？", "Enable this user?")
        : l("确认停用用户？", "Disable this user?"),
      content: l(
        `${targetUser.displayName || targetUser.username} 将被${nextActive ? "启用" : "停用"}。`,
        `${targetUser.displayName || targetUser.username} will be ${nextActive ? "enabled" : "disabled"}.`,
      ),
      okText: nextActive ? l("启用", "Enable") : l("停用", "Disable"),
      okButtonProps: { danger: !nextActive },
      cancelText: l("取消", "Cancel"),
      onOk: async () => {
        const updated = await api.updateAdminUser(targetUser.id, {
          isActive: nextActive,
        });
        setUsers((current) =>
          current.map((item) => (item.id === updated.id ? updated : item)),
        );
        message.success(
          nextActive
            ? l("用户已启用", "User enabled")
            : l("用户已停用", "User disabled"),
        );
      },
    });
  }

  function handleDeleteUser(targetUser: User) {
    modal.confirm({
      title: l("确认删除用户？", "Delete this user?"),
      content: l(
        `删除 ${targetUser.displayName || targetUser.username} 后无法恢复。`,
        `Deleting ${targetUser.displayName || targetUser.username} cannot be undone.`,
      ),
      okText: l("删除", "Delete"),
      okButtonProps: { danger: true },
      cancelText: l("取消", "Cancel"),
      onOk: async () => {
        await api.deleteAdminUser(targetUser.id);
        setUsers((current) =>
          current.filter((item) => item.id !== targetUser.id),
        );
        message.success(l("用户已删除", "User deleted"));
      },
    });
  }

  function handleResetUserPassword(targetUser: User) {
    modal.confirm({
      title: l("确认重置密码？", "Reset this password?"),
      content: l(
        `${targetUser.displayName || targetUser.username} 的当前密码将失效。`,
        `The current password for ${targetUser.displayName || targetUser.username} will stop working.`,
      ),
      okText: l("重置", "Reset"),
      cancelText: l("取消", "Cancel"),
      onOk: async () => {
        const result = await api.resetAdminUserPassword(targetUser.id);
        showGeneratedPasswordModal({
          title: l("密码重置成功", "Password reset"),
          username: result.username,
          password: result.generatedPassword,
        });
      },
    });
  }

  function handleRoleApplicationReview(
    application: RoleApplicationListItem,
    action: "approve" | "reject",
  ) {
    let reviewNote = "";
    modal.confirm({
      title:
        action === "approve"
          ? l(
              "确认通过科研用户申请？",
              "Approve this research-user application?",
            )
          : l(
              "确认拒绝科研用户申请？",
              "Reject this research-user application?",
            ),
      content: (
        <div className="admin-page-stack">
          <Typography.Paragraph>
            {application.user.displayName || application.user.username}：
            {application.reason}
          </Typography.Paragraph>
          <Input.TextArea
            placeholder={
              action === "approve"
                ? l("可填写审核说明", "Optional review note")
                : l("请填写拒绝原因", "Enter a reason for rejection")
            }
            maxLength={500}
            showCount
            onChange={(event) => {
              reviewNote = event.target.value;
            }}
          />
        </div>
      ),
      okText: action === "approve" ? l("通过", "Approve") : l("拒绝", "Reject"),
      okButtonProps: { danger: action === "reject" },
      cancelText: l("取消", "Cancel"),
      onOk: async () => {
        if (action === "reject" && !reviewNote.trim()) {
          message.error(l("请填写拒绝原因", "Enter a reason for rejection"));
          return Promise.reject();
        }
        const updated = await api.reviewRoleApplication(application.id, {
          action,
          reviewNote: reviewNote.trim(),
        });
        setRoleApplications((current) =>
          current.map((item) => (item.id === updated.id ? updated : item)),
        );
        await loadAuthData();
        message.success(
          action === "approve"
            ? l("科研用户申请已通过", "Research-user application approved")
            : l("科研用户申请已拒绝", "Research-user application rejected"),
        );
      },
    });
  }

  function openPermissionDrawer(group: Group) {
    setGroupDrafts((current) => ({
      ...current,
      [group.id]: current[group.id] ?? group.permissions,
    }));
    setPermissionGroup(group);
  }

  function closePermissionDrawer() {
    setPermissionGroup(null);
  }

  async function handleSaveGroup(group: Group) {
    if (!canManagePermissions || !canEditGroupPermissions(group)) return;
    const updated = await api.updateAdminGroup(group.id, {
      permissions: groupDrafts[group.id] ?? [],
    });
    setGroups((current) =>
      current.map((item) => (item.id === updated.id ? updated : item)),
    );
    setGroupDrafts((current) => ({
      ...current,
      [updated.id]: updated.permissions,
    }));
    setPermissionGroup(null);
    message.success(
      l(`${updated.name}权限已保存`, `${updated.name} permissions saved`),
    );
  }

  function handleGroupPermissionChange(group: Group, values: string[]) {
    const lockedPermissions = group.lockedPermissions ?? [];
    const missingLockedPermissions = lockedPermissions.filter(
      (permission) => !values.includes(permission),
    );
    if (missingLockedPermissions.length > 0) {
      message.warning(
        l(
          "系统锁定角色必须保留锁定权限",
          "System-locked roles must retain their locked permissions",
        ),
      );
    }
    setGroupDrafts((current) => ({
      ...current,
      [group.id]: Array.from(new Set([...values, ...lockedPermissions])),
    }));
  }

  async function handleDeleteGroup(group: Group) {
    if (!canManagePermissions || group.isProtected) return;
    await api.deleteAdminGroup(group.id);
    setGroups((current) => current.filter((item) => item.id !== group.id));
    setGroupDrafts((current) => {
      const next = { ...current };
      delete next[group.id];
      return next;
    });
    message.success(l("角色已删除", "Role deleted"));
  }

  async function handleSaveUserGroups() {
    if (
      !groupUser ||
      !canManageAuth ||
      groupUser.id === user?.id ||
      hasLockedGroupMembership(groupUser, groups)
    ) {
      return;
    }
    if (guestRoleId && selectedGroupIds.includes(guestRoleId)) {
      message.error(
        l(
          "游客角色仅供系统 guest 账号使用，不能分配给其他账号",
          "The guest role is reserved for the system guest account and cannot be assigned to other accounts",
        ),
      );
      return;
    }
    const updated = await api.updateAdminUserGroups(groupUser.id, {
      groupIds: selectedGroupIds as [number, ...number[]],
    });
    setUsers((current) =>
      current.map((user) => (user.id === updated.id ? updated : user)),
    );
    setGroupUser(null);
    message.success(l("角色归属已保存", "Role assignments saved"));
    await loadAuthData();
  }

  async function handleSaveUserPermissions() {
    if (
      !permissionUser ||
      !canManagePermissions ||
      permissionUser.id === user?.id
    ) {
      return;
    }
    const updated = await api.updateAdminUserPermissions(permissionUser.id, {
      directPermissions: userPermissionDrafts[permissionUser.id] ?? [],
      disabledPermissions:
        userDisabledPermissionDrafts[permissionUser.id] ?? [],
      operationLogGroupIds: userLogGroupDrafts[permissionUser.id] ?? [],
    });
    setUsers((current) =>
      current.map((item) => (item.id === updated.id ? updated : item)),
    );
    setUserPermissionDrafts((current) => ({
      ...current,
      [updated.id]: updated.directPermissions ?? [],
    }));
    setUserLogGroupDrafts((current) => ({
      ...current,
      [updated.id]: updated.operationLogGroupIds ?? [],
    }));
    setUserDisabledPermissionDrafts((current) => ({
      ...current,
      [updated.id]: updated.disabledPermissions ?? [],
    }));
    setPermissionUser(null);
    message.success(l("用户权限已保存", "User permissions saved"));
  }

  if (!canManageAuth) {
    return (
      <Result
        status="403"
        title={l(
          "无权限访问认证授权",
          "No permission to access authentication and authorization",
        )}
      />
    );
  }

  if (activeSection === "groups" && !canManagePermissions) {
    return (
      <Result
        status="403"
        title={l(
          "无权限访问角色权限",
          "No permission to access role permissions",
        )}
      />
    );
  }

  return (
    <div className="admin-page-stack">
      {activeSection === "users" ? (
        <Spin spinning={loading}>
          <div className="admin-page-stack">
            <UserSummaryCards metrics={userStats} />
            <ProTable<RoleApplicationListItem>
              className="admin-table"
              rowKey="id"
              headerTitle={
                <Space>
                  <span>{l("科研用户申请", "Research-user applications")}</span>
                  <Tag color="processing">
                    {l("待审核", "Pending")}{" "}
                    {
                      roleApplications.filter(
                        (item) => item.status === "pending",
                      ).length
                    }
                  </Tag>
                </Space>
              }
              columns={roleApplicationColumns}
              dataSource={roleApplications}
              cardBordered
              options={false}
              pagination={false}
              scroll={{ x: 1060 }}
              search={false}
              locale={{
                emptyText: l(
                  "暂无科研用户申请",
                  "No research-user applications",
                ),
              }}
            />
            <ProTable<User>
              className="admin-table"
              rowKey="id"
              headerTitle={l("用户列表", "Users")}
              columns={userColumns}
              dataSource={sortedUsers}
              cardBordered
              options={false}
              pagination={false}
              scroll={{ x: 840 }}
              search={false}
              toolBarRender={() =>
                canCreateUser
                  ? [
                      <Button
                        key="create"
                        type="primary"
                        icon={<PlusOutlined />}
                        onClick={() => {
                          createUserForm.setFieldsValue({ isActive: true });
                          setCreateUserOpen(true);
                        }}
                      >
                        {l("新建用户", "Create user")}
                      </Button>,
                    ]
                  : []
              }
            />
          </div>
        </Spin>
      ) : (
        <Spin spinning={loading}>
          <div className="admin-page-stack">
            <RolePresetGuide />
            <div className="admin-table-scroll-shell">
              <ProTable<Group>
                className="admin-table"
                rowKey="id"
                headerTitle={l("角色列表", "Roles")}
                columns={groupColumns}
                dataSource={groups}
                cardBordered
                options={false}
                pagination={false}
                scroll={{ x: "100%" }}
                search={false}
                toolBarRender={() => [
                  <Button
                    key="create"
                    type="primary"
                    icon={<PlusOutlined />}
                    onClick={() => setCreateGroupOpen(true)}
                  >
                    {l("新建角色", "Create role")}
                  </Button>,
                ]}
              />
            </div>
          </div>
        </Spin>
      )}

      <Drawer
        title={l("用户详情", "User details")}
        open={Boolean(activeUser)}
        onClose={() => setActiveUser(null)}
        size="large"
      >
        {activeUser ? (
          <div className="admin-user-drawer">
            <UserIdentity
              user={activeUser}
              title={
                <Typography.Title level={4} style={{ margin: 0 }}>
                  {activeUser.displayName || activeUser.username}
                </Typography.Title>
              }
              description={activeUser.email || l("未设置邮箱", "No email")}
              size={44}
            />
            <dl>
              <dt>{l("用户名", "Username")}</dt>
              <dd>
                <UserIdentity user={activeUser} title={activeUser.username} />
              </dd>
              <dt>{l("部门", "Department")}</dt>
              <dd>{activeUser.department || l("未设置", "Not set")}</dd>
              <dt>{l("状态", "Status")}</dt>
              <dd>
                {activeUser.isActive ? (
                  <Tag color="success">{l("启用", "Enabled")}</Tag>
                ) : (
                  <Tag color="error">{l("停用", "Disabled")}</Tag>
                )}
              </dd>
              <dt>{l("角色", "Roles")}</dt>
              <dd>
                <Space size={[6, 6]} wrap>
                  {activeUser.groupIds.length > 0 ? (
                    activeUser.groupIds.map((groupId) => (
                      <Tag key={groupId} color="green">
                        {groupNameById.get(groupId) ?? `#${groupId}`}
                      </Tag>
                    ))
                  ) : (
                    <Tag>{l("未分配角色", "No roles assigned")}</Tag>
                  )}
                </Space>
              </dd>
              <dt>{l("单独授予权限", "Direct permissions")}</dt>
              <dd>
                {(activeUser.directPermissions ?? []).length > 0 ? (
                  <PermissionTags
                    permissionIds={activeUser.directPermissions ?? []}
                    permissionLabelById={permissionLabelById}
                    maxVisible={8}
                  />
                ) : (
                  <Tag>{l("未单独授予", "None granted directly")}</Tag>
                )}
              </dd>
              <dt>{l("角色继承权限", "Inherited role permissions")}</dt>
              <dd>
                {(activeUser.groupPermissions ?? []).length > 0 ? (
                  <PermissionTags
                    permissionIds={activeUser.groupPermissions ?? []}
                    permissionLabelById={permissionLabelById}
                    maxVisible={10}
                  />
                ) : (
                  <Tag>{l("未继承", "None inherited")}</Tag>
                )}
              </dd>
              <dt>{l("实际生效权限", "Effective permissions")}</dt>
              <dd>
                <PermissionTags
                  permissionIds={activeUser.effectivePermissions ?? []}
                  permissionLabelById={permissionLabelById}
                  maxVisible={10}
                />
              </dd>
              <dt>{l("可查看日志角色", "Roles whose logs can be viewed")}</dt>
              <dd>
                <GroupTags
                  groupIds={activeUser.operationLogGroupIds ?? []}
                  groupNameById={groupNameById}
                  emptyText={l("未配置", "Not configured")}
                />
              </dd>
            </dl>
          </div>
        ) : (
          <Empty />
        )}
      </Drawer>

      <Drawer
        title={l("用户日志", "User logs")}
        open={Boolean(logUser)}
        onClose={() => setLogUser(null)}
        size="large"
      >
        {logUser ? (
          <div className="admin-page-stack">
            <UserIdentity
              user={logUser}
              title={
                <Typography.Text strong>
                  {logUser.displayName || logUser.username}
                </Typography.Text>
              }
            />
            <ProTable<AdminOperationLog>
              className="admin-table"
              rowKey="id"
              headerTitle={l("日志列表", "Logs")}
              columns={userLogColumns}
              cardBordered
              options={false}
              search={false}
              pagination={{
                pageSize: 10,
                showSizeChanger: false,
              }}
              scroll={{ x: "100%" }}
              request={async (params) => {
                const result = await api.adminOperationLogs({
                  current: params.current,
                  pageSize: params.pageSize,
                  userId: logUser.id,
                });
                return {
                  data: result.items,
                  total: result.total,
                  success: true,
                };
              }}
            />
          </div>
        ) : null}
      </Drawer>

      <Drawer
        title={l("设置角色", "Assign roles")}
        open={Boolean(groupUser)}
        onClose={() => setGroupUser(null)}
        extra={
          <Button type="primary" onClick={handleSaveUserGroups}>
            {l("保存", "Save")}
          </Button>
        }
      >
        {groupUser ? (
          <div className="admin-page-stack">
            <Typography.Text strong>{groupUser.displayName}</Typography.Text>
            <Select
              mode="multiple"
              value={selectedGroupIds}
              options={groupOptions}
              onChange={setSelectedGroupIds}
              style={{ width: "100%" }}
            />
            <Typography.Text type="secondary">
              {l(
                "游客角色仅供系统 guest 账号使用，不能分配给其他账号。",
                "The guest role is reserved for the system guest account and cannot be assigned to other accounts.",
              )}
            </Typography.Text>
          </div>
        ) : null}
      </Drawer>

      <Drawer
        title={l("设置用户权限", "Set user permissions")}
        open={Boolean(permissionUser)}
        onClose={() => setPermissionUser(null)}
        size="large"
        extra={
          <Button type="primary" onClick={handleSaveUserPermissions}>
            {l("保存", "Save")}
          </Button>
        }
      >
        {permissionUser ? (
          <div className="admin-page-stack">
            <UserIdentity
              user={permissionUser}
              title={
                <Typography.Text strong>
                  {permissionUser.displayName || permissionUser.username}
                </Typography.Text>
              }
              description={l(
                "开关控制实际生效权限；来自角色的权限标记为「角色继承」，关闭后写入「单独关闭」。",
                "Switches control effective permissions. Permissions supplied by roles are marked Inherited; turning one off records a direct denial.",
              )}
            />
            <div className="admin-permission-effective">
              <Typography.Text strong>
                {l("可查看日志角色", "Roles whose logs can be viewed")}
              </Typography.Text>
              <Typography.Text type="secondary">
                {l(
                  "仅在该用户具备「查看指定角色日志」权限时生效。",
                  "This applies only when the user has permission to view logs for specified roles.",
                )}
              </Typography.Text>
              <Select
                mode="multiple"
                value={
                  userLogGroupDrafts[permissionUser.id] ??
                  permissionUser.operationLogGroupIds ??
                  []
                }
                options={groups.map((group) => ({
                  label: builtinRoleDisplayName(group.name, english),
                  value: group.id,
                }))}
                onChange={(values) => {
                  setUserLogGroupDrafts((current) => ({
                    ...current,
                    [permissionUser.id]: values.map(Number),
                  }));
                }}
                placeholder={l(
                  "选择允许查看日志的角色",
                  "Select roles whose logs may be viewed",
                )}
                style={{ width: "100%" }}
              />
            </div>
            <PermissionPanel
              mode="user"
              availablePermissions={availablePermissions}
              directPermissions={
                userPermissionDrafts[permissionUser.id] ??
                permissionUser.directPermissions ??
                []
              }
              groupPermissions={permissionUser.groupPermissions ?? []}
              disabledPermissions={
                userDisabledPermissionDrafts[permissionUser.id] ??
                permissionUser.disabledPermissions ??
                []
              }
              onChange={(values) => {
                setUserPermissionDrafts((current) => ({
                  ...current,
                  [permissionUser.id]: values.directPermissions,
                }));
                setUserDisabledPermissionDrafts((current) => ({
                  ...current,
                  [permissionUser.id]: values.disabledPermissions,
                }));
              }}
            />
          </div>
        ) : null}
      </Drawer>

      <Modal
        title={l("新建角色", "Create role")}
        open={createGroupOpen}
        onOk={handleCreateGroup}
        onCancel={() => setCreateGroupOpen(false)}
        destroyOnHidden
      >
        <Form form={createGroupForm} layout="vertical">
          <Form.Item
            name="name"
            label={l("角色名称", "Role name")}
            rules={[
              {
                required: true,
                message: l("请输入角色名称", "Enter a role name"),
              },
            ]}
          >
            <Input />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        title={l("角色权限", "Role permissions")}
        open={Boolean(permissionGroup)}
        onClose={closePermissionDrawer}
        size="large"
        extra={
          <Button
            type="primary"
            onClick={() => {
              if (permissionGroup) {
                void handleSaveGroup(permissionGroup);
              }
            }}
          >
            {l("保存", "Save")}
          </Button>
        }
      >
        {permissionGroup ? (
          <div className="admin-page-stack">
            <Typography.Text strong>{permissionGroup.name}</Typography.Text>
            {permissionGroup.lockedPermissions.length > 0 && (
              <Alert
                type="warning"
                showIcon
                title={l(
                  "系统锁定角色必须保留锁定权限，不允许修改",
                  "System-locked roles must retain their locked permissions",
                )}
              />
            )}
            <PermissionPanel
              mode="group"
              availablePermissions={availablePermissions}
              selected={
                groupDrafts[permissionGroup.id] ?? permissionGroup.permissions
              }
              lockedPermissions={permissionGroup.lockedPermissions}
              onChange={(values) =>
                handleGroupPermissionChange(permissionGroup, values)
              }
            />
          </div>
        ) : null}
        {availablePermissions.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : null}
      </Drawer>

      <Modal
        title={l("新建用户", "Create user")}
        open={createUserOpen}
        onOk={handleCreateUser}
        onCancel={() => setCreateUserOpen(false)}
        destroyOnHidden
      >
        <Form
          form={createUserForm}
          layout="vertical"
          initialValues={{ isActive: true, groupIds: [] }}
        >
          <Form.Item
            name="username"
            label={l("用户名", "Username")}
            rules={[
              {
                required: true,
                message: l("请输入用户名", "Enter a username"),
              },
            ]}
          >
            <Input autoComplete="off" />
          </Form.Item>
          <Form.Item
            name="groupIds"
            label={l("角色", "Roles")}
            extra={l(
              "游客角色仅供系统 guest 账号使用，不能分配给其他账号。",
              "The guest role is reserved for the system guest account and cannot be assigned to other accounts.",
            )}
            rules={[
              {
                required: true,
                message: l("请选择角色", "Select at least one role"),
              },
            ]}
          >
            <Select mode="multiple" options={groupOptions} />
          </Form.Item>
          <Form.Item name="displayName" label={l("显示名称", "Display name")}>
            <Input />
          </Form.Item>
          <Form.Item
            name="email"
            label={l("邮箱", "Email")}
            rules={[
              {
                required: true,
                message: l("请输入邮箱", "Enter an email address"),
              },
              {
                type: "email",
                message: l("请输入有效邮箱", "Enter a valid email address"),
              },
            ]}
          >
            <Input />
          </Form.Item>
          <Form.Item name="department" label={l("部门", "Department")}>
            <Input />
          </Form.Item>
          <Form.Item
            name="isActive"
            label={l("启用账号", "Enable account")}
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

type FormValidationError = {
  errorFields?: { errors: string[] }[];
};

function RolePresetGuide() {
  const english = useEnglishLanguage();
  const l = (zh: string, en: string) => localText(english, zh, en);
  return (
    <Alert
      type="info"
      showIcon
      title={l("内置角色权限基线", "Built-in role permission baseline")}
      description={
        <Space size={[8, 8]} wrap>
          {builtinRoleOrder.map((roleName) => {
            const roleInfo = builtinRoleInfo[roleName];
            if (!roleInfo) return null;
            return (
              <Tooltip
                key={roleName}
                title={
                  english
                    ? builtinRoleInfoEnglish[roleName]?.summary
                    : roleInfo.summary
                }
              >
                <Tag color={roleInfo.color}>
                  {builtinRoleDisplayName(roleName, english)}
                </Tag>
              </Tooltip>
            );
          })}
        </Space>
      }
    />
  );
}

function GroupTags({
  groupIds,
  groupNameById,
  maxVisible = 6,
  emptyText,
}: {
  groupIds: number[];
  groupNameById: Map<number, string>;
  maxVisible?: number;
  emptyText?: string;
}) {
  const english = useEnglishLanguage();
  const resolvedEmptyText =
    emptyText ?? (english ? "No roles assigned" : "未分配角色");
  if (groupIds.length === 0) {
    return <Tag>{resolvedEmptyText}</Tag>;
  }
  const visibleIds = groupIds.slice(0, maxVisible);
  const hiddenCount = groupIds.length - visibleIds.length;
  return (
    <Space size={[4, 4]} wrap>
      {visibleIds.map((groupId) => (
        <Tag key={groupId} color="green">
          {groupNameById.get(groupId) ?? `#${groupId}`}
        </Tag>
      ))}
      {hiddenCount > 0 ? <Tag color="default">+{hiddenCount}</Tag> : null}
    </Space>
  );
}

function PermissionTags({
  permissionIds,
  permissionLabelById,
  maxVisible,
}: {
  permissionIds: string[];
  permissionLabelById: Map<string, string>;
  maxVisible: number;
}) {
  const visibleIds = permissionIds.slice(0, maxVisible);
  const hiddenCount = permissionIds.length - visibleIds.length;
  return (
    <Space size={[4, 4]} wrap>
      {visibleIds.map((permissionId) => (
        <Tag key={permissionId} color="green">
          {permissionLabelById.get(permissionId) ?? permissionId}
        </Tag>
      ))}
      {hiddenCount > 0 ? <Tag color="default">+{hiddenCount}</Tag> : null}
    </Space>
  );
}

function formOrApiError(error: unknown, fallback: string) {
  if (isFormValidationError(error)) {
    return error.errorFields?.[0]?.errors[0] ?? fallback;
  }
  return error instanceof Error ? error.message : fallback;
}

function isFormValidationError(error: unknown): error is FormValidationError {
  return typeof error === "object" && error !== null && "errorFields" in error;
}

function isGroupMembershipLocked(group: Group) {
  return group.isProtected && group.lockedPermissions.length > 0;
}

function hasLockedGroupMembership(user: User, groups: Group[]) {
  const lockedGroupIds = new Set(
    groups.filter(isGroupMembershipLocked).map((group) => group.id),
  );
  return user.groupIds.some((groupId) => lockedGroupIds.has(groupId));
}

function isGuestAccount(user: User) {
  return user.username === "guest";
}

function isGuestRole(group: Group) {
  return group.name === "游客";
}

function builtinRoleDisplayName(roleName: string, english: boolean) {
  return english
    ? (builtinRoleInfoEnglish[roleName]?.name ?? roleName)
    : roleName;
}

function UserIdentity({
  user,
  title,
  description,
  size = 32,
}: {
  user: Pick<User, "avatarUrl">;
  title: ReactNode;
  description?: ReactNode;
  size?: number;
}) {
  return (
    <Space className="admin-user-identity" size={10} align="center">
      <Avatar
        size={size}
        src={user.avatarUrl || undefined}
        icon={<UserOutlined />}
      />
      <Space orientation="vertical" size={0}>
        {typeof title === "string" ? (
          <Typography.Text>{title}</Typography.Text>
        ) : (
          title
        )}
        {description ? (
          <Typography.Text type="secondary" ellipsis>
            {description}
          </Typography.Text>
        ) : null}
      </Space>
    </Space>
  );
}

function canEditGroupPermissions(group: Group) {
  return group.lockedPermissions.length === 0;
}
