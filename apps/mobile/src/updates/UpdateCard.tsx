import { Text, View } from "react-native";
import { useTrackingStatus } from "../tracking/status";
import { Body, Button, ErrorText, useTheme } from "../ui";
import { megabytes } from "./logic";
import { useAppUpdate } from "./provider";

/**
 * What the driver or owner can do about an update: restart into one that has already downloaded, or download and install a newer app. With
 * `always` (the More screen) it also shows the installed version and a check button. Nothing is installed during a trip, since installing
 * closes the app.
 */
export function UpdateCard({ always }: { always?: boolean }) {
  const t = useTheme();
  const u = useAppUpdate();
  const trip = useTrackingStatus().on;
  const somethingToDo = u.otaReady || u.release !== null;
  if (!always && !somethingToDo) return null;

  return (
    <View style={{ padding: 16, borderRadius: 12, backgroundColor: t.surface, gap: 8 }}>
      {always && (
        <Body muted>
          FleetTms {u.installedVersion}
          {u.installedCode !== null ? ` (build ${u.installedCode})` : ""}
        </Body>
      )}
      {u.otaReady && (
        <>
          <Text style={{ color: t.text, fontWeight: "700" }}>An update is ready</Text>
          <Body muted>
            It changes how the app looks and works. Your saved work stays on the phone.
          </Body>
          {trip ? (
            <Body muted>
              A trip is being recorded, so it will be applied the next time you open the app.
            </Body>
          ) : (
            <Button label="Restart to update" onPress={() => void u.restart()} />
          )}
        </>
      )}
      {u.release && (
        <>
          <Text style={{ color: t.text, fontWeight: "700" }}>New version {u.release.version}</Text>
          {u.release.notes ? <Body muted>{u.release.notes}</Body> : null}
          {u.phase === "idle" || u.phase === "failed" ? (
            <>
              <Body muted>
                {megabytes(u.release.size_bytes)
                  ? `About ${megabytes(u.release.size_bytes)}. `
                  : ""}
                Use Wi-Fi if you can. You choose when to install it.
              </Body>
              <ErrorText message={u.error} />
              <Button
                label={u.phase === "failed" ? "Try again" : "Download update"}
                onPress={() => void u.download()}
              />
            </>
          ) : null}
          {u.phase === "downloading" && <Body>Downloading {Math.round(u.progress * 100)}%</Body>}
          {(u.phase === "ready" || u.phase === "installing") && (
            <>
              <Body muted>
                Downloaded. When you install it, Android may ask you to allow FleetTms to install
                apps: allow it, then tap Install again.
              </Body>
              {trip ? (
                <Body muted>A trip is being recorded. Install it after you end the trip.</Body>
              ) : (
                <Button
                  label="Install now"
                  onPress={() => void u.install()}
                  busy={u.phase === "installing"}
                />
              )}
            </>
          )}
        </>
      )}
      {always && !somethingToDo && (
        <>
          <Body muted>
            {u.checking
              ? "Looking for updates..."
              : u.upToDate
                ? "You have the latest version."
                : "Updates are checked when you open the app."}
          </Body>
          <Button
            label="Check for updates"
            kind="secondary"
            onPress={() => void u.checkNow()}
            busy={u.checking}
          />
        </>
      )}
    </View>
  );
}
