// Wire contract with the Python server (babycue_server/protocol.py);
// tests/test_wire_contract.py fails if the two drift apart.
//
// Baby phone -> server: POST /frame with one JPEG as the body.
// Server -> parent phone: GET /view, multipart/x-mixed-replace (an <img> plays it).
// GET /status returns JSON about the relay. GET /ca.crt is the local certificate authority.
export const DEFAULT_PORT = 8080;
export const INGEST_PATH = '/ingest';
export const FRAME_PATH = '/frame';
export const VIEW_PATH = '/view';
export const STATUS_PATH = '/status';
export const CA_PATH = '/ca.crt';
export const MAX_FRAME_BYTES = 8 * 1024 * 1024;
