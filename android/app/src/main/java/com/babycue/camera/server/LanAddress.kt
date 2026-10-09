package com.babycue.camera.server

import java.net.Inet4Address
import java.net.NetworkInterface

/** One IPv4 address on one interface. */
data class NetAddress(val interfaceName: String, val ipv4: String, val isUp: Boolean)

/** Finds the IPv4 address other devices on the same Wi-Fi/LAN can reach. Needs no permission. */
object LanAddress {

    /**
     * Picks the best private IPv4 address. Wi-Fi, hotspot and Ethernet interfaces win; cellular,
     * VPN and tunnel interfaces are ignored (their private-looking addresses are not reachable from the PC).
     */
    fun pick(candidates: List<NetAddress>): String? =
        candidates
            .filter { it.isUp && isPrivateIpv4(it.ipv4) }
            .mapNotNull { c -> rank(c.interfaceName)?.let { it to c.ipv4 } }
            .minByOrNull { it.first }
            ?.second

    /** Current address, or null when not on a LAN. */
    fun find(): String? = try {
        val all = ArrayList<NetAddress>()
        for (ni in NetworkInterface.getNetworkInterfaces()?.toList().orEmpty()) {
            val up = try { ni.isUp && !ni.isLoopback } catch (_: Exception) { false }
            for (a in ni.inetAddresses.toList()) {
                if (a is Inet4Address && !a.isLoopbackAddress) all.add(NetAddress(ni.name, a.hostAddress ?: continue, up))
            }
        }
        pick(all)
    } catch (_: Exception) {
        null
    }

    internal fun isPrivateIpv4(ip: String): Boolean {
        val p = ip.split('.').map { it.toIntOrNull() ?: return false }
        if (p.size != 4 || p.any { it !in 0..255 }) return false
        return p[0] == 10 || (p[0] == 172 && p[1] in 16..31) || (p[0] == 192 && p[1] == 168)
    }

    /** 0 = preferred (Wi-Fi/AP/Ethernet), 1 = unknown name, null = never use. */
    private fun rank(name: String): Int? {
        val n = name.lowercase()
        return when {
            EXCLUDED.any { n.startsWith(it) } -> null
            PREFERRED.any { n.startsWith(it) } -> 0
            else -> 1
        }
    }

    private val PREFERRED = listOf("wlan", "swlan", "ap", "eth", "en")
    private val EXCLUDED = listOf("rmnet", "ccmni", "tun", "tap", "ppp", "dummy", "lo", "v4-", "ip6tnl", "p2p", "docker", "veth", "vpn")
}
