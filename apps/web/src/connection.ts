import { createConnectionState } from "@fleettms/api-client";

/** Shared by the api client (which reports into it) and the loading bar and offline banner (which read it). */
export const connection = createConnectionState();
