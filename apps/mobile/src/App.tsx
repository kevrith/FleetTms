import { StatusBar } from "expo-status-bar";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { AuthProvider } from "./auth";
import { RootNavigation } from "./navigation";

export default function App() {
  return (
    <SafeAreaProvider>
      <AuthProvider>
        <RootNavigation />
      </AuthProvider>
      <StatusBar style="auto" />
    </SafeAreaProvider>
  );
}
