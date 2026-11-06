// Paquete binario del dashboard: [1 byte: longitud][camera_id UTF-8][JPEG]. Idéntico a backend/ws_handler.frame_packet.
export const DEFAULT_CAMERA = "cam-1";

export function decodeFrame(buffer: ArrayBuffer): { cameraId: string; jpeg: Blob } | null {
  const bytes = new Uint8Array(buffer);
  const length = bytes[0];
  if (!length || bytes.length <= 1 + length) return null;
  try {
    const cameraId = new TextDecoder("utf-8", { fatal: true }).decode(bytes.subarray(1, 1 + length));
    return { cameraId, jpeg: new Blob([bytes.subarray(1 + length)], { type: "image/jpeg" }) };
  } catch { return null; }
}

export function encodeFrame(cameraId: string, jpeg: Uint8Array): ArrayBuffer {
  const name = new TextEncoder().encode(cameraId);
  const packet = new Uint8Array(1 + name.length + jpeg.length);
  packet[0] = name.length;
  packet.set(name, 1);
  packet.set(jpeg, 1 + name.length);
  return packet.buffer;
}
