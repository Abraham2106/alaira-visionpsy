// @vitest-environment node
import type { IncomingMessage } from "node:http";
import { expect, it } from "vitest";
import { localSessionAllowed } from "../local-session";

function request(remoteAddress: string, host = "192.168.40.8:5175", origin = `https://${host}`, site = "same-origin") {
  return { socket: { remoteAddress }, headers: { host, origin, "sec-fetch-site": site } } as IncomingMessage;
}

it("permite únicamente esta PC con origen y host locales coincidentes", () => {
  const addresses = ["192.168.40.8"];
  expect(localSessionAllowed(request("192.168.40.8"), true, addresses)).toBe(true);
  expect(localSessionAllowed(request("::ffff:127.0.0.1", "localhost:5175"), true, addresses)).toBe(true);
  expect(localSessionAllowed(request("192.168.40.9"), true, addresses)).toBe(false);
  expect(localSessionAllowed(request("127.0.0.1", "attacker.example:5175"), true, addresses)).toBe(false);
  expect(localSessionAllowed(request("127.0.0.1", undefined, "https://attacker.example"), true, addresses)).toBe(false);
  expect(localSessionAllowed(request("127.0.0.1", undefined, undefined, "cross-site"), true, addresses)).toBe(false);
  const forged = request("192.168.40.9");
  forged.headers["x-forwarded-for"] = "127.0.0.1";
  expect(localSessionAllowed(forged, true, addresses)).toBe(false);
});
