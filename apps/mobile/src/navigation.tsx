import { Ionicons } from "@expo/vector-icons";
import { colors, tapTarget } from "@fleettms/design-tokens";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { DarkTheme, DefaultTheme, NavigationContainer } from "@react-navigation/native";
import { ActivityIndicator, useColorScheme, View } from "react-native";
import { useAuth } from "./auth";
import { Screen } from "./ui";
import HomeScreen from "./screens/Home";
import LoginScreen from "./screens/Login";
import ExpensesScreen from "./screens/Expenses";
import MoreScreen from "./screens/More";
import NoticesScreen from "./screens/Notices";
import TripPanel from "./screens/TripPanel";
import TwoFactorScreen from "./screens/TwoFactor";
import VehiclesScreen from "./screens/Vehicles";

const Tab = createBottomTabNavigator();

type IconName = React.ComponentProps<typeof Ionicons>["name"];
interface TabDef {
  name: string;
  icon: IconName;
  component: React.ComponentType;
}

const Trips = () => (
  <Screen>
    <TripPanel />
  </Screen>
);

// Driver tabs per masterplan Section 6; the owner view is leaner until later sprints add content.
const DRIVER_TABS: TabDef[] = [
  { name: "Home", icon: "home-outline", component: HomeScreen },
  { name: "Trips", icon: "navigate-outline", component: Trips },
  { name: "Expenses", icon: "cash-outline", component: ExpensesScreen },
  { name: "More", icon: "menu-outline", component: MoreScreen },
];
const OWNER_TABS: TabDef[] = [
  { name: "Home", icon: "home-outline", component: HomeScreen },
  { name: "Vehicles", icon: "bus-outline", component: VehiclesScreen },
  { name: "More", icon: "menu-outline", component: MoreScreen },
];

function Tabs({ tabs }: { tabs: TabDef[] }) {
  return (
    <Tab.Navigator
      screenOptions={{
        tabBarStyle: { height: tapTarget + 12 },
        tabBarLabelStyle: { fontSize: 13 },
      }}
    >
      {tabs.map(({ name, icon, component }) => (
        <Tab.Screen
          key={name}
          name={name}
          component={component}
          options={{
            tabBarIcon: ({ color, size }) => <Ionicons name={icon} size={size} color={color} />,
          }}
        />
      ))}
    </Tab.Navigator>
  );
}

function Gate() {
  const { me, loading, view } = useAuth();
  if (loading) {
    return (
      <View style={{ flex: 1, justifyContent: "center" }}>
        <ActivityIndicator size="large" />
      </View>
    );
  }
  if (!me) return <LoginScreen />;
  if (me.mfa_setup_required) return <TwoFactorScreen />;
  if (me.pending_documents.length > 0) return <NoticesScreen docs={me.pending_documents} />;
  // Re-keyed by view so switching Owner/Driver rebuilds the tabs.
  return <Tabs key={view} tabs={view === "driver" ? DRIVER_TABS : OWNER_TABS} />;
}

export function RootNavigation() {
  const dark = useColorScheme() === "dark";
  const base = dark ? DarkTheme : DefaultTheme;
  return (
    <NavigationContainer theme={{ ...base, colors: { ...base.colors, primary: colors.brand } }}>
      <Gate />
    </NavigationContainer>
  );
}
