import { files, vault } from "./offline/device";
import { createReadCache } from "./offline/readcache";

/** Saved replies to GETs, shared by the api client (which fills it) and sign-out (which empties it). */
export const readCache = createReadCache({ files, vault });
