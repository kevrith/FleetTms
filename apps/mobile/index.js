import { registerRootComponent } from "expo";
import App from "./src/App";
// The background location task has to be defined when the app loads, so it exists when the system wakes the app for a fix.
import "./src/tracking/task";

registerRootComponent(App);
