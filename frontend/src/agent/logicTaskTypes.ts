import type { ComponentProps, ReactNode } from "react";
import type WorkflowResults from "./WorkflowResults";
import type { AgentResearchIntent } from "../api/generated/types.gen";

export type LogicTaskProps = ComponentProps<typeof WorkflowResults> & {
  inputReview?: ReactNode;
  inputSummary?: AgentResearchIntent["inputSummary"];
  initialThinking?: string;
  onAdjustInputs?: () => void;
  onReviewRetained?: () => void;
};
