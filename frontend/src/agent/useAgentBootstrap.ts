import { useEffect, useState } from "react";
import { agentApi } from "../api/agent";
import type { AgentBootstrap } from "../api/generated/types.gen";
import { useAppContext } from "../contexts/AppContext";
import { useProjectContext } from "../projects/ProjectContext";

export function useAgentBootstrap() {
  const { user } = useAppContext();
  const project = useProjectContext()?.current;
  const [value, setValue] = useState<AgentBootstrap | null>(null);
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    setValue(null);
    if (!user || user.username === "guest" || user.roles.includes("游客"))
      return;
    const load = async () => {
      try {
        const result = await agentApi.bootstrap();
        if (!disposed) setValue(result);
      } catch {
        if (!disposed) setValue(null);
      }
      if (!disposed) timer = setTimeout(load, 30000);
    };
    void load();
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [user?.id, project]);
  return value;
}
