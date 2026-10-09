package com.babycue.camera.ui

import com.babycue.camera.server.MjpegProtocol
import com.babycue.camera.server.ServerState

enum class ServerLineKind { STOPPED, STARTING, RUNNING, RUNNING_NO_ADDRESS, FAILED }

/** What the server section of the screen shows. Only [ServerLineKind.RUNNING] means a client can actually connect. */
data class ServerLine(
    val kind: ServerLineKind,
    val url: String? = null,
    val port: Int? = null,
    val clients: Int = 0,
    val error: String? = null,
)

fun streamUrl(ip: String, port: Int): String = "http://$ip:$port${MjpegProtocol.STREAM_PATH}"

fun serverLine(state: ServerState, lanIp: String?, clients: Int): ServerLine = when (state) {
    ServerState.Stopped -> ServerLine(ServerLineKind.STOPPED)
    ServerState.Starting -> ServerLine(ServerLineKind.STARTING)
    is ServerState.Failed -> ServerLine(ServerLineKind.FAILED, error = state.message)
    is ServerState.Running ->
        if (lanIp == null) ServerLine(ServerLineKind.RUNNING_NO_ADDRESS, port = state.port, clients = clients)
        else ServerLine(ServerLineKind.RUNNING, url = streamUrl(lanIp, state.port), port = state.port, clients = clients)
}
