// Wire contract with the Python server (babycue_server/protocol.py);
// tests/test_wire_contract.py fails if the two drift apart.
//
// Baby phone -> server: POST /frame with one JPEG as the body.
// Server -> parent phone: GET /view, multipart/x-mixed-replace (an <img> plays it).
// GET /status returns JSON about the relay. GET /ca.crt is the local certificate authority.
// /baby and /detections are the server's database: the baby's name and the detection log.
export const DEFAULT_PORT = 8080;
export const INGEST_PATH = '/ingest';
export const FRAME_PATH = '/frame';
export const VIEW_PATH = '/view';
export const STATUS_PATH = '/status';
export const CA_PATH = '/ca.crt';
/** GET: { baby: { name, created_at } | null }. POST { name } names (or renames) the baby. */
export const BABY_PATH = '/baby';
/** GET ?limit=N: { detections: [...] }, newest first, each with its local date and time. */
export const DETECTIONS_PATH = '/detections';
export const MAX_FRAME_BYTES = 8 * 1024 * 1024;
