import { Box, Button, Flex, Grid, Heading, IconButton, Stack, Text } from "@chakra-ui/react";
import { CaretDown, Check, Package, X } from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { DashboardProduct } from "../api/types";
import { cleanDisplayText } from "../utils/displayText";

export interface ProductGroup {
  id: string;
  label: string;
  terms: string[];
}

export const GUARDIAN_PRODUCT_GROUPS: ProductGroup[] = [
  { id: "all", label: "All product groups", terms: [] },
  { id: "guardian-exclusive", label: "Độc quyền Guardian", terms: ["guardian", "eco garden", "happy mask", "number eight", "botaneco", "kusabana", "mannings"] },
  { id: "facial-skincare", label: "Chăm sóc da mặt", terms: ["cham soc da mat", "skincare", "skin care", "cleanser", "sua rua mat", "tay trang", "toner", "serum", "mat na", "mask", "kem duong", "chong nang", "cerave", "la roche", "duong da"] },
  { id: "makeup", label: "Trang điểm", terms: ["trang diem", "makeup", "cosmetic", "lipstick", "son", "mascara", "eyeliner", "kem nen", "cushion", "phan", "co trang diem"] },
  { id: "body-care", label: "Chăm sóc cơ thể", terms: ["cham soc co the", "body", "sua tam", "xa phong", "khu mui", "duong the", "tay long", "cao rau", "ve sinh ca nhan"] },
  { id: "health-care", label: "Chăm sóc sức khỏe", terms: ["cham soc suc khoe", "health", "vitamin", "omega", "thuc pham chuc nang", "xuong khop", "ho hap", "tieu hoa", "y te"] },
  { id: "personal-care", label: "Chăm sóc cá nhân", terms: ["cham soc ca nhan", "oral", "dental", "rang mieng", "kem danh rang", "nuoc suc mieng", "ban chai", "khau trang", "khan giay", "nuoc hoa"] },
  { id: "hair-care", label: "Chăm sóc tóc", terms: ["cham soc toc", "hair", "dau goi", "dau xa", "duong toc", "nhuom toc", "tao kieu toc"] },
  { id: "mom-baby", label: "Mẹ Và Bé", terms: ["me va be", "baby", "mom", "me", "be", "ta", "khan uot", "tam goi cho be", "cham soc be"] },
];

interface ProductGroupSelectProps {
  products: DashboardProduct[];
  selectedGroupId: string;
  onChange: (groupId: string) => void;
}

function normalize(value: string): string {
  return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase();
}

function productHaystack(product: DashboardProduct): string {
  return normalize([product.name, product.shortName, product.sku, product.category, product.pack, product.id]
    .filter((value): value is string => Boolean(value))
    .map(cleanDisplayText)
    .join(" "));
}

export function productMatchesGroup(product: DashboardProduct, group: ProductGroup): boolean {
  if (group.id === "all") return true;
  const haystack = productHaystack(product);
  return group.terms.some((term) => haystack.includes(normalize(term)));
}

export function ProductGroupSelect({ products, selectedGroupId, onChange }: ProductGroupSelectProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const selectedGroup = GUARDIAN_PRODUCT_GROUPS.find((group) => group.id === selectedGroupId) ?? GUARDIAN_PRODUCT_GROUPS[0]!;

  useEffect(() => {
    const closeOutside = (event: PointerEvent) => { if (!rootRef.current?.contains(event.target as Node)) setOpen(false); };
    const closeEscape = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeEscape);
    };
  }, []);

  const counts = useMemo(() => new Map(GUARDIAN_PRODUCT_GROUPS.map((group) => [
    group.id,
    group.id === "all" ? products.length : products.filter((product) => productMatchesGroup(product, group)).length,
  ])), [products]);

  const selectGroup = (groupId: string) => {
    onChange(groupId);
    setOpen(false);
  };

  return (
    <Box position="relative" ref={rootRef} minW={{ md: "340px" }}>
      <Button
        width="full"
        height="44px"
        variant="outline"
        bg="surface"
        _hover={{ bg: "surface" }}
        _expanded={{ bg: "surface" }}
        px="3"
        justifyContent="space-between"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={`Change product group. ${selectedGroup.label}.`}
      >
        <Flex align="center" gap="2" minW="0">
          <Package size={18} />
          <Text fontWeight="700" truncate>{selectedGroup.label}</Text>
          <Text color="muted" fontSize="sm" display={{ base: "none", md: "inline" }}>{counts.get(selectedGroup.id) ?? 0}</Text>
        </Flex>
        <CaretDown size={15} />
      </Button>

      {open && (
        <Box position="absolute" zIndex="dropdown" top="calc(100% + 8px)" right="0" width={{ base: "min(92vw, 420px)", md: "420px" }} maxH="min(620px, 75vh)" overflow="hidden" bg="surface" borderWidth="1px" borderColor="border" borderRadius="panel" boxShadow="xl" role="dialog" aria-label="Filter by product group">
          <Flex px="5" py="4" align="center" justify="space-between" borderBottomWidth="1px" borderColor="border">
            <Heading size="md">Product group</Heading>
            <IconButton size="sm" variant="ghost" aria-label="Close product group filter" onClick={() => setOpen(false)}><X size={17} /></IconButton>
          </Flex>
          <Stack maxH="430px" overflowY="auto" gap="0" divideY="1px" divideColor="border">
            {GUARDIAN_PRODUCT_GROUPS.map((group) => {
              const isSelected = group.id === selectedGroup.id;
              return (
                <Grid as="button" key={group.id} gridTemplateColumns="auto minmax(0, 1fr) auto" gap="3" alignItems="center" px="5" py="3.5" cursor="pointer" textAlign="left" bg={isSelected ? "orange.50" : "surface"} _dark={{ bg: isSelected ? "#24150d" : "surface" }} _hover={{ bg: "subtle" }} onClick={() => selectGroup(group.id)}>
                  <Flex w="5" h="5" flex="0 0 auto" align="center" justify="center" borderWidth="1px" borderColor={isSelected ? "accent" : "border"} borderRadius="4px" bg={isSelected ? "accent" : "surface"} color="white">
                    {isSelected && <Check size={13} weight="bold" />}
                  </Flex>
                  <Text fontWeight="650">{group.label}</Text>
                  <Text color="muted" fontWeight="700">{counts.get(group.id) ?? 0}</Text>
                </Grid>
              );
            })}
          </Stack>
        </Box>
      )}
    </Box>
  );
}
