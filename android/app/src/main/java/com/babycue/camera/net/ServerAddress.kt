package com.babycue.camera.net

/** The PC running the BabyCue server, as typed by the user (`192.168.1.20` or `192.168.1.20:8080`). */
data class ServerAddress(val host: String, val port: Int) {
    val ingestUrl: String get() = "http://$host:$port${WireProtocol.INGEST_PATH}"
    val viewUrl: String get() = "http://$host:$port${WireProtocol.VIEW_PATH}"
    val display: String get() = "$host:$port"

    companion object {
        private val HOST = Regex("[A-Za-z0-9._-]+")

        /** Returns null if [text] is not a usable `host[:port]` (an `http://` prefix and path are tolerated). */
        fun parse(text: String): ServerAddress? {
            var rest = text.trim()
            if (rest.startsWith("http://", ignoreCase = true)) rest = rest.substring(7)
            rest = rest.substringBefore('/')
            if (rest.isEmpty()) return null
            val colon = rest.lastIndexOf(':')
            val host = if (colon >= 0) rest.substring(0, colon) else rest
            val port = if (colon >= 0) rest.substring(colon + 1).toIntOrNull() ?: return null else WireProtocol.DEFAULT_PORT
            if (!HOST.matches(host) || port !in 1..65535) return null
            return ServerAddress(host, port)
        }
    }
}
