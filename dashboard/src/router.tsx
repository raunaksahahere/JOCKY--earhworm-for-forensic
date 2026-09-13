import { QueryClient } from "@tanstack/react-query";
import { createHashHistory, createRouter } from "@tanstack/react-router";
import { routeTree } from "./routeTree.gen";

export const getRouter = () => {
  const queryClient = new QueryClient();
  const hashHistory = createHashHistory();

  return createRouter({
    routeTree,
    context: { queryClient },
    history: hashHistory,
    scrollRestoration: true,
    defaultPreloadStaleTime: 0,
  });
};
