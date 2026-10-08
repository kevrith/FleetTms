import { Ionicons } from "@expo/vector-icons";
import { colors, tapTarget } from "@fleettms/design-tokens";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { DarkTheme, DefaultTheme, NavigationContainer } from "@react-navigation/native";
import { useEffect, useState } from "react";
import { ActivityIndicator, AppState, ScrollView, useColorScheme, View } from "react-native";
import { api } from "./api";
import { useAuth } from "./auth";
import { StatusBar } from "expo-status-bar";
import { Screen, useTheme } from "./ui";
import HomeScreen from "./screens/Home";
import LoginScreen from "./screens/Login";
import ExpensesScreen from "./screens/Expenses";
import FleetScreen from "./screens/Fleet";
import MessagesScreen from "./screens/Messages";
import MoneyScreen from "./screens/Money";
import MoreScreen from "./screens/More";
import NoticesScreen from "./screens/Notices";
import TripPanel from "./screens/TripPanel";
import { PartsScreen, WorkOrdersScreen } from "./screens/Workshop";
import TwoFactorScreen from "./screens/TwoFactor";
import VehiclesScreen from "./screens/Vehicles";

const Tab = createBottomTabNavigator();

type IconName = React.ComponentProps<typeof Ionicons>["name"];
interface TabDef {
  name: string;
  icon: IconName;
  component: React.ComponentType;
}

// Scrolls: the pre-trip inspection list is longer than the screen.
const Trips = () => (
  <Screen>
    <ScrollView
      contentContainerStyle={{ gap: 16, paddingVertical: 16 }}
      keyboardShouldPersistTaps="handled"
    >
      <TripPanel />
    </ScrollView>
  </Screen>
);

// Driver tabs per masterplan Section 6; the owner view is leaner until later sprints add content.
const DRIVER_TABS: TabDef[] = [
  { name: "Home", icon: "home-outline", component: HomeScreen },
  { name: "Trips", icon: "navigate-outline", component: Trips },
  { name: "Expenses", icon: "cash-outline", component: ExpensesScreen },
  { name: "Messages", icon: "mail-outline", component: MessagesScreen },
  { name: "More", icon: "menu-outline", component: MoreScreen },
];
const OWNER_TABS: TabDef[] = [
  { name: "Home", icon: "home-outline", component: HomeScreen },
  { name: "Vehicles", icon: "bus-outline", component: VehiclesScreen },
  { name: "More", icon: "menu-outline", component: MoreScreen },
];

const MONEY_TAB: TabDef = { name: "Money", icon: "wallet-outline", component: MoneyScreen };

const WORKSHOP_TAB: TabDef = {
  name: "Workshop",
  icon: "construct-outline",
  component: WorkOrdersScreen,
};
// The workshop and storekeeper role: work orders and the parts store, nothing else of the business.
const WORKSHOP_TABS: TabDef[] = [
  { name: "Work orders", icon: "construct-outline", component: WorkOrdersScreen },
  { name: "Parts", icon: "cube-outline", component: PartsScreen },
  { name: "More", icon: "menu-outline", component: MoreScreen },
];

/** How many office messages the driver has not opened yet; checked every minute and whenever the app returns. */
function useUnreadMessages(enabled: boolean) {
  const [unread, setUnread] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    const check = () =>
      api
        .myMessages()
        .then((r) => setUnread(r.unread))
        .catch(() => {}); // offline: keep the last count
    void check();
    const timer = setInterval(check, 60_000);
    const sub = AppState.addEventListener("change", (s) => s === "active" && void check());
    return () => {
      clearInterval(timer);
      sub.remove();
    };
  }, [enabled]);
  return unread;
}

function Tabs({ tabs }: { tabs: TabDef[] }) {
  const t = useTheme();
  const unread = useUnreadMessages(tabs.some((tab) => tab.name === "Messages"));
  return (
    <>
      {/* the navy header sits behind the clock and battery */}
      <StatusBar style="light" />
      <Tab.Navigator
        screenOptions={{
          headerStyle: { backgroundColor: colors.navy },
          headerTintColor: "#ffffff",
          headerTitleStyle: { fontWeight: "700" },
          tabBarActiveTintColor: t.action,
          tabBarInactiveTintColor: t.muted,
          tabBarStyle: {
            height: tapTarget + 12,
            backgroundColor: t.bg,
            borderTopColor: t.line,
          },
          tabBarLabelStyle: { fontSize: tabs.length > 5 ? 11 : 13 }, // six tabs leave each label little room
        }}
      >
        {tabs.map(({ name, icon, component }) => (
          <Tab.Screen
            key={name}
            name={name}
            component={component}
            options={{
              tabBarBadge: name === "Messages" && unread > 0 ? unread : undefined,
              tabBarIcon: ({ color, size }) => <Ionicons name={icon} size={size} color={color} />,
            }}
          />
        ))}
      </Tab.Navigator>
    </>
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
  const can = (p: string) => me.permissions.includes(p);
  const workshopOnly = can("workshop.manage") && !can("vehicles.view");
  const money = ["expenses.approve_limit", "reconciliations.approve", "floats.manage"].some(can);
  const office = [
    ...OWNER_TABS.slice(0, -1),
    ...(money ? [MONEY_TAB] : []),
    ...(can("workshop.manage") ? [WORKSHOP_TAB] : []),
    ...OWNER_TABS.slice(-1),
  ];
  const withMap = can("livemap.view")
    ? [
        ...office.slice(0, -1),
        { name: "Map", icon: "location-outline" as IconName, component: FleetScreen },
        ...office.slice(-1),
      ]
    : office;
  const tabs = view === "driver" ? DRIVER_TABS : workshopOnly ? WORKSHOP_TABS : withMap;
  return <Tabs key={view} tabs={tabs} />;
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
