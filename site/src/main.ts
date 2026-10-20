import "@fontsource/cormorant-garamond/400.css";
import "@fontsource/cormorant-garamond/400-italic.css";
import "@fontsource/cormorant-garamond/500.css";
import "@fontsource/cormorant-garamond/600.css";
import "@fontsource/jost/400.css";
import "@fontsource/jost/500.css";
import "@fontsource/jost/700.css";
import "./styles.css";
import { navigate, route } from "./router";

route("/", "home", () => import("./pages/home"), () => "Breakup Board");
route("/event/:id", "event", () => import("./pages/event"), (p) => p.id);
route("/reentry", "reentry", () => import("./pages/reentry"), () => "Reentry Watch");
route("/scorecard", "scorecard", () => import("./pages/scorecard"), () => "Rocket Stage Scorecard");
route("/sql", "sql", () => import("./pages/sqllab"), () => "SQL Lab");
route("/methods", "methods", () => import("./pages/methods"), () => "Methods");
route("/status", "status", () => import("./pages/status"), () => "Status");

const root = document.getElementById("main")!;
window.addEventListener("hashchange", () => navigate(root));
navigate(root);
