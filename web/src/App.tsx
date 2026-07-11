import { Box, Button, ChakraProvider, Flex, Grid, IconButton, Spinner, Stack, Text, Heading } from "@chakra-ui/react";
import { Database, Pulse, SidebarSimple, UploadSimple, WarningCircle } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { fetchDashboard } from "./api/client";
import { sanitizeDashboardMessages } from "./api/dashboardMessages";
import type { DashboardData } from "./api/types";
import { Dashboard } from "./components/Dashboard";
import { ReviewImportPanel } from "./components/ReviewImportPanel";
import { system } from "./theme";

type ActiveTab = "dashboard" | "import";

const stateBox = { maxW: "720px", mx: "auto", mt: "10", p: { base: "6", md: "9" }, bg: "surface", borderWidth: "1px", borderColor: "border", borderRadius: "panel" } as const;

function GuardianPalmBrand({ compact = false }: { compact?: boolean }) {
  return (
    <Flex align="center" gap="2.5" minW="0" aria-label="Guardian Palm">
      <Flex align="center" justify="center" w={compact ? "10" : "104px"} h={compact ? "10" : "8"} px={compact ? "0" : "2.5"} bg="brand.500" borderRadius="control" overflow="hidden" flexShrink="0">
        <Box asChild h={compact ? "8" : "5"} w={compact ? "8" : "auto"} maxW="100%" objectFit="contain">
          <img src={compact ? "/favicon.webp" : "/logo.svg"} alt="" aria-hidden="true" />
        </Box>
      </Flex>
      {!compact && <Text color="ink" fontSize="xl" fontWeight="750" lineHeight="1">Palm</Text>}
    </Flex>
  );
}

function AppContent() {
  const [activeTab, setActiveTab] = useState<ActiveTab>("import");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const requestRef = useRef<AbortController | null>(null);

  useLayoutEffect(() => {
    document.documentElement.classList.remove("dark");
    document.documentElement.style.colorScheme = "light";
  }, []);

  const load = useCallback(async () => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setLoading(true);
    setError("");
    try {
      setData(await fetchDashboard(controller.signal));
    } catch (cause) {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "The dashboard request failed.");
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    if (activeTab === "dashboard" && !data) void load();
    return () => requestRef.current?.abort();
  }, [activeTab, data, load]);

  const isEmpty = data?.dataState === "empty";
  const hasNoProductGroups = data !== null && data.dataState !== "empty" && data.products.length === 0;
  const messages = data ? sanitizeDashboardMessages(data.messages) : [];
  const sidebarWidth = sidebarCollapsed ? "72px" : "220px";
  const tabButton = (tab: ActiveTab, label: string, icon: ReactNode) => (
    <Button
      justifyContent="flex-start"
      variant={activeTab === tab ? "subtle" : "ghost"}
      colorPalette={activeTab === tab ? "orange" : "gray"}
      px="3"
      onClick={() => setActiveTab(tab)}
      aria-current={activeTab === tab ? "page" : undefined}
    >
      {icon}
      {!sidebarCollapsed && label}
    </Button>
  );

  return (
    <Grid minH="100vh" bg="canvas" gridTemplateColumns={{ base: "1fr", lg: `${sidebarWidth} minmax(0, 1fr)` }} transition="grid-template-columns .2s ease">
      <Box asChild position="fixed" top="-20" left="4" zIndex="tooltip" px="4" py="2" bg="surface" _focus={{ top: "4" }}><a href="#main-content">Skip to content</a></Box>

      <Flex as="aside" display={{ base: "none", lg: "flex" }} position="sticky" top="0" h="100vh" direction="column" borderRightWidth="1px" borderColor="border" bg="surface" overflow="hidden">
        <Flex h="72px" px={sidebarCollapsed ? "5" : "6"} align="center" borderBottomWidth="1px" borderColor="border" color="accent">
          <GuardianPalmBrand compact={sidebarCollapsed} />
        </Flex>
        <Stack as="nav" aria-label="Primary navigation" p="3" gap="1" flex="1">
          {tabButton("dashboard", "Dashboard", <Pulse size={19} weight="fill" />)}
          {tabButton("import", "Import", <UploadSimple size={19} />)}
        </Stack>
        <IconButton m="3" variant="ghost" aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"} onClick={() => setSidebarCollapsed((value) => !value)}><SidebarSimple size={20} /></IconButton>
      </Flex>

      <Box minW="0">
        <Flex as="header" display={{ base: "flex", lg: "none" }} position="sticky" top="0" zIndex="docked" minH="72px" px={{ base: "4", md: "7" }} py="3" align="center" justify="space-between" gap="4" bg="surface" borderBottomWidth="1px" borderColor="border">
          <Flex align="center" minW="0">
            <Box display={{ base: "block", lg: "none" }}><GuardianPalmBrand compact /></Box>
          </Flex>
          <Flex align="center" justify="flex-end" gap="2" wrap="wrap">
            <Flex role="tablist" aria-label="Workspace sections" display={{ base: "flex", lg: "none" }} p="1" bg="subtle" borderRadius="control" gap="1">
              <Button role="tab" size="sm" variant={activeTab === "dashboard" ? "solid" : "ghost"} colorPalette="orange" onClick={() => setActiveTab("dashboard")} aria-selected={activeTab === "dashboard"}>Dashboard</Button>
              <Button role="tab" size="sm" variant={activeTab === "import" ? "solid" : "ghost"} colorPalette="orange" onClick={() => setActiveTab("import")} aria-selected={activeTab === "import"}>Import</Button>
            </Flex>
          </Flex>
        </Flex>

        <Box as="main" id="main-content" maxW="1500px" mx="auto" px={{ base: "4", md: "7", xl: "10" }} py={{ base: "6", md: "8" }}>
          {activeTab === "dashboard" && loading && !data && <Flex {...stateBox} aria-busy="true" aria-label="Loading dashboard" align="center" justify="center" gap="3"><Spinner color="accent" /><Text color="muted">Loading dashboard...</Text></Flex>}
          {activeTab === "dashboard" && error && !data && <Stack {...stateBox} role="alert" align="flex-start" gap="4"><WarningCircle size={30} color="var(--chakra-colors-danger)" weight="fill" /><Heading size="xl">Dashboard data could not be loaded</Heading><Text color="muted">{error}</Text><Button colorPalette="orange" onClick={() => void load()}>Retry dashboard</Button></Stack>}
          {activeTab === "dashboard" && data && error && <Flex mb="6" p="4" gap="3" borderLeftWidth="4px" borderColor="danger" bg="surface" role="alert"><WarningCircle size={20} /><Box><Text fontWeight="700">Update failed</Text><Text color="muted">{error}</Text></Box></Flex>}
          {activeTab === "dashboard" && data && (isEmpty || hasNoProductGroups) && <Stack {...stateBox} align="flex-start" gap="4"><Database size={30} /><Heading size="xl">{isEmpty ? "No product-attributed feedback is available" : "No Guardian product groups are available yet"}</Heading><Text color="muted">{messages[0] ?? "The backend has not returned enough product-linked records to build this dashboard."}</Text><Flex gap="6" wrap="wrap">{[[data.coverage.feedbackItems, "feedback items"], [data.coverage.analyzedItems, "analyzed"], [data.coverage.productAttributedItems, "product attributed"]].map(([value, label]) => <Box key={String(label)}><Text fontSize="xl" fontWeight="700">{Number(value).toLocaleString()}</Text><Text color="muted" fontSize="sm">{label}</Text></Box>)}</Flex></Stack>}
          {activeTab === "dashboard" && data && !isEmpty && !hasNoProductGroups && <Dashboard data={data} />}
          {activeTab === "import" && <ReviewImportPanel onImported={() => load()} />}
        </Box>
      </Box>
    </Grid>
  );
}

export function App() {
  return <ChakraProvider value={system}><AppContent /></ChakraProvider>;
}
