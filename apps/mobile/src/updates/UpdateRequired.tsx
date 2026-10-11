import { Linking, ScrollView, Text } from "react-native";
import { Body, Button, Screen, useTheme } from "../ui";
import { UpdateCard } from "./UpdateCard";
import { canSelfInstall } from "./logic";
import { useAppUpdate } from "./provider";
import { Platform } from "react-native";

const PLAY = "market://details?id=com.kastra.fleettms";
const DOWNLOAD_PAGE =
  "https://github.com/kevrith/FleetTms/releases/download/mobile-latest/fleettms.apk";

/** Shown instead of the app when the server will no longer serve this build. What the driver has saved stays on the phone. */
export function UpdateRequired() {
  const t = useTheme();
  const u = useAppUpdate();
  const self = canSelfInstall(u.distribution, Platform.OS);
  return (
    <Screen>
      <ScrollView contentContainerStyle={{ gap: 16, padding: 16, paddingTop: 48 }}>
        <Text style={{ color: t.text, fontSize: 26, fontWeight: "800" }}>
          Please update FleetTms
        </Text>
        <Body>
          This version of the app is too old to be used. Update it to carry on. Anything you saved
          on this phone is kept and will be sent after the update.
        </Body>
        {self ? (
          <>
            <UpdateCard />
            {!u.release && (
              <Button
                label={u.checking ? "Looking..." : "Look for the update"}
                onPress={() => void u.checkNow()}
                busy={u.checking}
              />
            )}
            <Button
              label="Open the download page"
              kind="secondary"
              onPress={() => void Linking.openURL(DOWNLOAD_PAGE)}
            />
          </>
        ) : u.distribution === "play" ? (
          <Button label="Open Google Play" onPress={() => void Linking.openURL(PLAY)} />
        ) : (
          <Button
            label="Open the download page"
            onPress={() => void Linking.openURL(DOWNLOAD_PAGE)}
          />
        )}
      </ScrollView>
    </Screen>
  );
}
