import { StatusBar } from "expo-status-bar";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { AuthProvider } from "./auth";
import { OfflineProvider } from "./offline/runtime";
import { RootNavigation } from "./navigation";
import { UpdatesProvider } from "./updates/provider";

export default function App() {
  return (
    <SafeAreaProvider>
      <AuthProvider>
        <UpdatesProvider>
          <OfflineProvider>
            <RootNavigation />
          </OfflineProvider>
        </UpdatesProvider>
      </AuthProvider>
      <StatusBar style="auto" />
    </SafeAreaProvider>
  );
}
