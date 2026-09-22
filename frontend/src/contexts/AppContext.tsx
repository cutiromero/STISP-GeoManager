import { createContext, useContext } from "react";
import type { Bootstrap, User } from "../types";

export interface AppContextValue {
  bootstrap: Bootstrap;
  user: User | null;
  setBootstrap: (bootstrap: Bootstrap) => void;
  setUser: (user: User | null) => void;
}

export const AppContext = createContext<AppContextValue | null>(null);

export function useAppContext(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) {
    throw new Error("useAppContext must be used within AppContext.Provider");
  }
  return ctx;
}
