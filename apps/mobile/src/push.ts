import Constants from "expo-constants";
import * as Notifications from "expo-notifications";
import { Platform } from "react-native";
import { api } from "./api";

/** The loud Android channel an SOS arrives on. The server names the same channel in each push. */
const SOS_CHANNEL = "sos";

// A push that arrives while the app is open is shown too, not swallowed.
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

/**
 * Asks to show notifications and tells the server this phone's push address, so an SOS reaches the owner with the app closed. It never
 * throws: a phone that refuses, has no push service, or a build without push set up simply goes on without it (the SOS text and the
 * banner on the home screen still work).
 */
export async function registerForPush(): Promise<void> {
  try {
    if (Platform.OS === "android") {
      await Notifications.setNotificationChannelAsync(SOS_CHANNEL, {
        name: "SOS and emergencies",
        importance: Notifications.AndroidImportance.MAX,
        vibrationPattern: [0, 500, 250, 500],
        lockscreenVisibility: Notifications.AndroidNotificationVisibility.PUBLIC,
      });
    }
    const current = await Notifications.getPermissionsAsync();
    const granted = current.granted || (await Notifications.requestPermissionsAsync()).granted;
    if (!granted) return;
    const projectId = Constants.expoConfig?.extra?.eas?.projectId as string | undefined;
    const token = (await Notifications.getExpoPushTokenAsync(projectId ? { projectId } : undefined))
      .data;
    await api.setPushToken(token);
  } catch {
    /* see the note above */
  }
}
