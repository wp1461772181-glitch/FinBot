import assert from "node:assert/strict";
import test from "node:test";
import { BACKSTAGE_TABS, PATTERNS, backstageTab, pathForSection, paths, sectionOfPath } from "../src/routes.mjs";
import { AREAS, activeArea, activeItem, areaItems, areaPath, needsLogin } from "../src/shell-nav.mjs";
import { pageItems } from "../src/command-items.mjs";
import { skeletonKind } from "../src/skeleton-kind.mjs";
import { navGroup } from "../src/workspace-sections.mjs";

test("后台 has an address and one per tab", () => {
  assert.deepEqual(BACKSTAGE_TABS, ["answers", "usage", "operations", "deliveries"]);
  assert.equal(PATTERNS.backstage, "/backstage");
  assert.equal(PATTERNS.backstageTab, "/backstage/:tab");
  assert.equal(paths.backstage(), "/backstage");
  for (const tab of BACKSTAGE_TABS) assert.equal(paths.backstage(tab), `/backstage/${tab}`);
  assert.equal(paths.backstage("nonsense"), "/backstage");
  assert.equal(backstageTab("usage"), "usage");
  assert.equal(backstageTab("nonsense"), "answers");
  assert.equal(backstageTab(undefined), "answers");
});

test("the address is its own area, the owner's alone", () => {
  assert.ok(AREAS.includes("backstage"));
  assert.equal(sectionOfPath("/backstage/usage"), "backstage");
  assert.equal(sectionOfPath("/backstage"), "backstage");
  assert.equal(navGroup("backstage"), "backstage");
  assert.equal(activeArea("/backstage/operations"), "backstage");
  assert.equal(activeItem("/backstage/operations"), null);
  assert.deepEqual(areaItems("backstage"), []);
  assert.equal(areaPath("backstage"), "/backstage");
  assert.equal(pathForSection("backstage"), "/backstage");
  for (const path of ["/backstage", "/backstage/answers", "/backstage/usage", "/backstage/deliveries"]) assert.equal(needsLogin(path), true, path);
  assert.equal(skeletonKind("/backstage/answers"), "table");
});

test("the palette offers the page to the owner and not to a guest", () => {
  assert.ok(pageItems({ personal: true }).some((p) => p.path === "/backstage"));
  assert.ok(!pageItems({ personal: false }).some((p) => p.path.startsWith("/backstage")));
});
