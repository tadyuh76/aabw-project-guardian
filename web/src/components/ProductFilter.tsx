import { Box, Button, Flex, Grid, Heading, IconButton, Input, Stack, Text } from "@chakra-ui/react";
import { CaretDown, Check, MagnifyingGlass, Package, X } from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { DashboardProduct } from "../api/types";

interface ProductFilterProps { products: DashboardProduct[]; selectedIds: string[]; onChange: (ids: string[]) => void; }

function productName(product: DashboardProduct): string {
  return product.shortName ?? product.name ?? `Unidentified product - ${product.id}`;
}

export function ProductFilter({ products, selectedIds, onChange }: ProductFilterProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);

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

  const visibleProducts = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    return normalized
      ? products.filter((product) => [product.name, product.shortName, product.sku, product.category, product.id].filter(Boolean).join(" ").toLocaleLowerCase().includes(normalized))
      : products;
  }, [products, query]);
  const selected = products.filter((product) => selectedIds.includes(product.id));
  const allSelected = products.length > 0 && selected.length === products.length;
  const feedback = selected.reduce((sum, product) => sum + product.totalFeedback, 0);
  const label = allSelected ? "Portfolio" : selected.length === 0 ? "No products" : selected.length === 1 ? productName(selected[0]!) : `${selected.length} selected`;
  const toggleProduct = (id: string) => onChange(selectedIds.includes(id) ? selectedIds.filter((item) => item !== id) : [...selectedIds, id]);
  const check = (checked: boolean) => (
    <Flex w="5" h="5" flex="0 0 auto" align="center" justify="center" borderWidth="1px" borderColor={checked ? "accent" : "border"} borderRadius="4px" bg={checked ? "accent" : "surface"} color="white">
      {checked && <Check size={13} weight="bold" />}
    </Flex>
  );

  return (
    <Box position="relative" ref={rootRef} minW={{ md: "320px" }}>
      <Button
        width="full"
        height="44px"
        variant="outline"
        px="3"
        justifyContent="space-between"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={`Change product scope. ${label}.`}
      >
        <Flex align="center" gap="2" minW="0">
          <Package size={18} />
          <Text fontWeight="700" truncate>{label}</Text>
          <Text color="muted" fontSize="sm" display={{ base: "none", md: "inline" }}>{feedback.toLocaleString()}</Text>
        </Flex>
        <CaretDown size={15} />
      </Button>

      {open && (
        <Box position="absolute" zIndex="dropdown" top="calc(100% + 8px)" right="0" width={{ base: "min(92vw, 520px)", md: "520px" }} maxH="min(640px, 75vh)" overflow="hidden" bg="surface" borderWidth="1px" borderColor="border" borderRadius="panel" boxShadow="xl" role="dialog" aria-label="Filter by products">
          <Flex px="5" py="4" align="center" justify="space-between" borderBottomWidth="1px" borderColor="border">
            <Heading size="md">Products</Heading>
            <IconButton size="sm" variant="ghost" aria-label="Close product filter" onClick={() => setOpen(false)}><X size={17} /></IconButton>
          </Flex>
          <Box p="4" borderBottomWidth="1px" borderColor="border">
            <Flex align="center" gap="2" px="3" borderWidth="1px" borderColor="border" borderRadius="control" bg="canvas">
              <MagnifyingGlass size={16} />
              <Input autoFocus aria-label="Search products" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search products" border="0" outline="0" />
            </Flex>
          </Box>
          <Button variant="ghost" borderRadius="0" h="auto" w="full" px="5" py="4" justifyContent="stretch" onClick={() => onChange(products.map((product) => product.id))}>
            <Flex align="center" gap="3" textAlign="left">{check(allSelected)}<Text fontWeight="700">Select all</Text></Flex>
          </Button>
          <Stack maxH="360px" overflowY="auto" gap="0" borderYWidth="1px" borderColor="border" divideY="1px" divideColor="border">
            {visibleProducts.map((product) => {
              const isSelected = selectedIds.includes(product.id);
              return (
                <Grid as="label" key={product.id} gridTemplateColumns="auto minmax(0, 1fr) auto" gap="3" alignItems="center" px="5" py="3" cursor="pointer" bg={isSelected ? "orange.50" : "surface"} _dark={{ bg: isSelected ? "#24150d" : "surface" }} _hover={{ bg: "subtle" }}>
                  <input className="visually-hidden" type="checkbox" checked={isSelected} onChange={() => toggleProduct(product.id)} />
                  {check(isSelected)}
                  <Box minW="0">
                    <Text fontWeight="650">{productName(product)}</Text>
                    <Text color="muted" fontSize="sm" truncate>{[product.sku, product.category, product.pack].filter(Boolean).join(" - ") || product.id}</Text>
                  </Box>
                  <Text fontWeight="700">{product.current.feedback.toLocaleString()}</Text>
                </Grid>
              );
            })}
            {visibleProducts.length === 0 && <Text p="6" color="muted" textAlign="center">No matches.</Text>}
          </Stack>
          <Flex px="5" py="3" align="center" justify="space-between">
            <Button size="sm" variant="ghost" colorPalette="orange" onClick={() => onChange([])}>Clear</Button>
            <Button size="sm" colorPalette="orange" onClick={() => setOpen(false)}>Done</Button>
          </Flex>
        </Box>
      )}
    </Box>
  );
}
