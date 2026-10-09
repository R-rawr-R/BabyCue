package com.babycue.camera.net

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ServerAddressTest {

    @Test
    fun hostAndPortAreParsed() {
        assertEquals(ServerAddress("192.168.1.20", 9000), ServerAddress.parse("192.168.1.20:9000"))
    }

    @Test
    fun portDefaultsToTheProtocolDefault() {
        assertEquals(ServerAddress("192.168.1.20", WireProtocol.DEFAULT_PORT), ServerAddress.parse("192.168.1.20"))
    }

    @Test
    fun schemePathAndWhitespaceAreTolerated() {
        assertEquals(ServerAddress("pc.local", 8080), ServerAddress.parse("  HTTP://pc.local:8080/view  "))
    }

    @Test
    fun unusableInputIsRejected() {
        for (bad in listOf("", "   ", ":8080", "host:", "host:abc", "host:0", "host:70000", "bad host", "a:b:c", "https://x")) {
            assertNull("\"$bad\" should be rejected", ServerAddress.parse(bad))
        }
    }

    @Test
    fun urlsUseTheWirePaths() {
        val a = ServerAddress("10.0.0.5", 8080)
        assertEquals("http://10.0.0.5:8080/ingest", a.ingestUrl)
        assertEquals("http://10.0.0.5:8080/view", a.viewUrl)
        assertEquals("10.0.0.5:8080", a.display)
    }
}
