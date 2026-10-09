package com.babycue.camera.server

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class LanAddressTest {
    private fun a(name: String, ip: String, up: Boolean = true) = NetAddress(name, ip, up)

    @Test
    fun picksWifiOverCellularEvenWhenCellularIsPrivate() {
        assertEquals("192.168.1.23", LanAddress.pick(listOf(a("rmnet_data0", "10.45.2.9"), a("wlan0", "192.168.1.23"))))
    }

    @Test
    fun ignoresVpnTunnelAndLoopback() {
        assertNull(LanAddress.pick(listOf(a("tun0", "10.8.0.2"), a("lo", "127.0.0.1"), a("ppp0", "10.1.1.1"))))
    }

    @Test
    fun ignoresDownInterfacesAndPublicOrLinkLocalAddresses() {
        assertNull(LanAddress.pick(listOf(a("wlan0", "192.168.1.5", up = false))))
        assertNull(LanAddress.pick(listOf(a("wlan0", "169.254.3.4"))))
        assertNull(LanAddress.pick(listOf(a("wlan0", "8.8.8.8"))))
    }

    @Test
    fun hotspotInterfaceIsUsable() {
        assertEquals("192.168.43.1", LanAddress.pick(listOf(a("rmnet0", "10.9.9.9"), a("ap0", "192.168.43.1"))))
    }

    @Test
    fun unknownInterfaceNameIsFallbackBelowWifi() {
        assertEquals("172.20.1.1", LanAddress.pick(listOf(a("foo0", "172.20.1.1"))))
        assertEquals("10.0.0.7", LanAddress.pick(listOf(a("foo0", "172.20.1.1"), a("wlan0", "10.0.0.7"))))
    }

    @Test
    fun privateRanges() {
        assertTrue(LanAddress.isPrivateIpv4("10.0.0.1"))
        assertTrue(LanAddress.isPrivateIpv4("172.16.0.1"))
        assertTrue(LanAddress.isPrivateIpv4("172.31.255.255"))
        assertTrue(LanAddress.isPrivateIpv4("192.168.0.1"))
        assertFalse(LanAddress.isPrivateIpv4("172.15.0.1"))
        assertFalse(LanAddress.isPrivateIpv4("172.32.0.1"))
        assertFalse(LanAddress.isPrivateIpv4("192.169.0.1"))
        assertFalse(LanAddress.isPrivateIpv4("999.1.1.1"))
        assertFalse(LanAddress.isPrivateIpv4("abc"))
    }

    @Test
    fun findNeverThrows() {
        LanAddress.find() // environment dependent result; must simply not throw
    }
}
