import {
  CheckCircleFilled,
  LockOutlined,
  MinusCircleOutlined,
} from "@ant-design/icons";
import { Space, Switch, Tag, Tooltip, Typography } from "antd";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { AdminPermissionItem } from "../types";

interface PermissionGroup {
  group: string;
  items: AdminPermissionItem[];
}

interface GroupModeProps {
  mode: "group";
  availablePermissions: AdminPermissionItem[];
  selected: string[];
  lockedPermissions?: string[];
  onChange: (permissionIds: string[]) => void;
}

interface UserModeProps {
  mode: "user";
  availablePermissions: AdminPermissionItem[];
  directPermissions: string[];
  groupPermissions: string[];
  disabledPermissions: string[];
  onChange: (values: {
    directPermissions: string[];
    disabledPermissions: string[];
  }) => void;
}

interface ProfileModeProps {
  mode: "profile";
  availablePermissions: AdminPermissionItem[];
  grantedPermissions: string[];
  disabledPermissions: string[];
  onChange: (permissionId: string, enabled: boolean) => void;
}

type PermissionPanelProps = GroupModeProps | UserModeProps | ProfileModeProps;

function groupPermissions(
  permissions: AdminPermissionItem[],
): PermissionGroup[] {
  const groups = new Map<string, AdminPermissionItem[]>();
  for (const perm of permissions) {
    const current = groups.get(perm.group) ?? [];
    current.push(perm);
    groups.set(perm.group, current);
  }
  return [...groups.entries()].map(([group, items]) => ({ group, items }));
}

export function PermissionPanel(props: PermissionPanelProps) {
  const english = useEnglish();
  const permGroups = useMemo(
    () => groupPermissions(props.availablePermissions),
    [props.availablePermissions],
  );

  if (permGroups.length === 0) {
    return (
      <Typography.Text type="secondary">
        {english ? "No configurable permissions" : "暂无可配置的权限项"}
      </Typography.Text>
    );
  }

  return (
    <div className="perm-panel">
      {permGroups.map((pg) => (
        <PermissionSection key={pg.group} permGroup={pg} {...props} />
      ))}
    </div>
  );
}

function PermissionSection({
  permGroup,
  ...props
}: { permGroup: PermissionGroup } & PermissionPanelProps) {
  const { group, items } = permGroup;

  const sectionState = useSectionState(items, props);

  return (
    <div className="perm-section">
      <div className="perm-section-header">
        <Space size={8} align="center">
          <Typography.Text strong className="perm-section-title">
            {group}
          </Typography.Text>
          <Tag className="perm-section-count">{sectionState.summary}</Tag>
        </Space>
        {sectionState.toggleable && (
          <Switch
            size="small"
            checked={sectionState.allEnabled}
            onChange={(checked) => sectionState.toggleAll(checked)}
          />
        )}
      </div>
      <div className="perm-section-body">
        {items.map((perm) => (
          <PermissionRow key={perm.id} permission={perm} {...props} />
        ))}
      </div>
    </div>
  );
}

function useSectionState(
  items: AdminPermissionItem[],
  props: PermissionPanelProps,
) {
  return useMemo(() => {
    const ids = items.map((i) => i.id);

    if (props.mode === "group") {
      const selectedSet = new Set(props.selected);
      const lockedSet = new Set(props.lockedPermissions ?? []);
      const editableIds = ids.filter((id) => !lockedSet.has(id));
      const enabledCount = ids.filter((id) => selectedSet.has(id)).length;
      const allEnabled = editableIds.every((id) => selectedSet.has(id));
      return {
        summary: `${enabledCount}/${ids.length}`,
        allEnabled,
        toggleable: editableIds.length > 0,
        toggleAll: (checked: boolean) => {
          const current = new Set(props.selected);
          for (const id of editableIds) {
            if (checked) current.add(id);
            else current.delete(id);
          }
          props.onChange([...current]);
        },
      };
    }

    if (props.mode === "user") {
      const directSet = new Set(props.directPermissions);
      const groupSet = new Set(props.groupPermissions);
      const disabledSet = new Set(props.disabledPermissions);
      const enabledCount = ids.filter(
        (id) => (directSet.has(id) || groupSet.has(id)) && !disabledSet.has(id),
      ).length;
      const allEnabled = ids.every(
        (id) => (directSet.has(id) || groupSet.has(id)) && !disabledSet.has(id),
      );
      return {
        summary: `${enabledCount}/${ids.length}`,
        allEnabled,
        toggleable: ids.length > 0,
        toggleAll: (checked: boolean) => {
          const nextDirect = new Set(props.directPermissions);
          const nextDisabled = new Set(props.disabledPermissions);
          for (const id of ids) {
            if (checked) {
              nextDisabled.delete(id);
              if (!groupSet.has(id)) nextDirect.add(id);
            } else if (directSet.has(id) || groupSet.has(id)) {
              nextDisabled.add(id);
            }
          }
          props.onChange({
            directPermissions: [...nextDirect],
            disabledPermissions: [...nextDisabled],
          });
        },
      };
    }

    const grantedSet = new Set(props.grantedPermissions);
    const disabledSet = new Set(props.disabledPermissions);
    const grantedIds = ids.filter((id) => grantedSet.has(id));
    const enabledCount = grantedIds.filter((id) => !disabledSet.has(id)).length;
    const allEnabled =
      grantedIds.length > 0 && grantedIds.every((id) => !disabledSet.has(id));
    return {
      summary: `${enabledCount}/${ids.length}`,
      allEnabled,
      toggleable: grantedIds.length > 0,
      toggleAll: (checked: boolean) => {
        for (const id of grantedIds) {
          props.onChange(id, checked);
        }
      },
    };
  }, [items, props]);
}

function PermissionRow({
  permission,
  ...props
}: { permission: AdminPermissionItem } & PermissionPanelProps) {
  if (props.mode === "group") {
    return <GroupPermissionRow permission={permission} {...props} />;
  }
  if (props.mode === "user") {
    return <UserPermissionRow permission={permission} {...props} />;
  }
  return <ProfilePermissionRow permission={permission} {...props} />;
}

function GroupPermissionRow({
  permission,
  selected,
  lockedPermissions,
  onChange,
}: {
  permission: AdminPermissionItem;
} & GroupModeProps) {
  const isSelected = selected.includes(permission.id);
  const isLocked = (lockedPermissions ?? []).includes(permission.id);
  const english = useEnglish();

  const handleChange = (checked: boolean) => {
    if (isLocked) return;
    if (checked) {
      onChange([...selected, permission.id]);
    } else {
      onChange(selected.filter((id) => id !== permission.id));
    }
  };

  return (
    <div
      className={`perm-row ${isSelected ? "perm-row--active" : ""} ${isLocked ? "perm-row--locked" : ""}`}
    >
      <div className="perm-row-info">
        <Typography.Text strong className="perm-row-label">
          {permission.label}
        </Typography.Text>
        <Typography.Text type="secondary" className="perm-row-id">
          {permission.id}
        </Typography.Text>
      </div>
      <div className="perm-row-actions">
        {isLocked && (
          <Tooltip
            title={
              english
                ? "System-locked permission; cannot be changed"
                : "系统锁定权限，不可修改"
            }
          >
            <Tag icon={<LockOutlined />} color="default">
              {english ? "Locked" : "锁定"}
            </Tag>
          </Tooltip>
        )}
        <Switch
          size="small"
          checked={isSelected}
          disabled={isLocked}
          onChange={handleChange}
        />
      </div>
    </div>
  );
}

function UserPermissionRow({
  permission,
  directPermissions,
  groupPermissions,
  disabledPermissions,
  onChange,
}: {
  permission: AdminPermissionItem;
} & UserModeProps) {
  const isDirect = directPermissions.includes(permission.id);
  const isFromGroup = groupPermissions.includes(permission.id);
  const isDisabled = disabledPermissions.includes(permission.id);
  const isGranted = isDirect || isFromGroup;
  const isEnabled = isGranted && !isDisabled;
  const english = useEnglish();

  const handleChange = (checked: boolean) => {
    const nextDirect = new Set(directPermissions);
    const nextDisabled = new Set(disabledPermissions);
    if (checked) {
      nextDisabled.delete(permission.id);
      if (!isFromGroup) {
        nextDirect.add(permission.id);
      }
    } else {
      if (isGranted) {
        nextDisabled.add(permission.id);
      }
    }
    onChange({
      directPermissions: [...nextDirect],
      disabledPermissions: [...nextDisabled],
    });
  };

  return (
    <div
      className={`perm-row ${isEnabled ? "perm-row--active" : ""} ${isFromGroup ? "perm-row--inherited" : ""}`}
    >
      <div className="perm-row-info">
        <Typography.Text strong className="perm-row-label">
          {permission.label}
        </Typography.Text>
        <Typography.Text type="secondary" className="perm-row-id">
          {permission.id}
        </Typography.Text>
      </div>
      <div className="perm-row-actions">
        {isFromGroup && (
          <Tag icon={<CheckCircleFilled />} color="blue">
            {english ? "Inherited from role" : "角色继承"}
          </Tag>
        )}
        {isDirect && !isFromGroup && !isDisabled && (
          <Tag icon={<CheckCircleFilled />} color="green">
            {english ? "Direct grant" : "单独授予"}
          </Tag>
        )}
        {isGranted && isDisabled && (
          <Tag color="orange">{english ? "Directly disabled" : "单独关闭"}</Tag>
        )}
        {!isGranted && (
          <Tag icon={<MinusCircleOutlined />} color="default">
            {english ? "Not granted" : "未授予"}
          </Tag>
        )}
        <Switch size="small" checked={isEnabled} onChange={handleChange} />
      </div>
    </div>
  );
}

function ProfilePermissionRow({
  permission,
  grantedPermissions,
  disabledPermissions,
  onChange,
}: {
  permission: AdminPermissionItem;
} & ProfileModeProps) {
  const granted = grantedPermissions.includes(permission.id);
  const disabled = disabledPermissions.includes(permission.id);
  const enabled = granted && !disabled;
  const english = useEnglish();

  return (
    <div
      className={`perm-row ${enabled ? "perm-row--active" : ""} ${!granted ? "perm-row--unavailable" : ""}`}
    >
      <div className="perm-row-info">
        <Typography.Text strong className="perm-row-label">
          {permission.label}
        </Typography.Text>
        <Typography.Text type="secondary" className="perm-row-id">
          {permission.id}
        </Typography.Text>
      </div>
      <div className="perm-row-actions">
        {!granted && (
          <Tag icon={<MinusCircleOutlined />} color="default">
            {english ? "Not granted" : "未授予"}
          </Tag>
        )}
        {granted && enabled && (
          <Tag icon={<CheckCircleFilled />} color="green">
            {english ? "Enabled" : "已开启"}
          </Tag>
        )}
        {granted && !enabled && (
          <Tag color="orange">{english ? "Disabled" : "已关闭"}</Tag>
        )}
        <Switch
          size="small"
          checked={enabled}
          disabled={!granted}
          onChange={(checked) => onChange(permission.id, checked)}
        />
      </div>
    </div>
  );
}

function useEnglish() {
  const { i18n } = useTranslation();
  return i18n.resolvedLanguage?.toLowerCase().startsWith("en") ?? false;
}
