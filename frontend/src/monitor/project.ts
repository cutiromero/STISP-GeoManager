import { useProjectContext } from "../projects/ProjectContext";

export const monitorPath = "/results/ecology-monitor";
export const monitorFeature = "ecology_monitor";

export function useMonitorProject() {
  const context = useProjectContext();
  return context?.projects.find(
    (project) =>
      String(project.id) === context.current &&
      project.isActive &&
      project.enabledFeatures?.includes(monitorFeature),
  );
}
