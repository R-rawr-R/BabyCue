package com.babycue.camera.net

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test

class WireProtocolTest {

    @Test
    fun lengthPrefixIsFourBytesBigEndian() {
        assertArrayEquals(byteArrayOf(0, 0, 0, 0), WireProtocol.lengthPrefix(0))
        assertArrayEquals(byteArrayOf(0, 0, 1, 0), WireProtocol.lengthPrefix(256))
        assertArrayEquals(byteArrayOf(0, 1, 0x02, 0x03), WireProtocol.lengthPrefix(0x010203))
        assertArrayEquals(
            byteArrayOf(0x00, 0x80.toByte(), 0x00, 0x00),
            WireProtocol.lengthPrefix(WireProtocol.MAX_FRAME_BYTES),
        )
        assertEquals(WireProtocol.LENGTH_PREFIX_BYTES, WireProtocol.lengthPrefix(1).size)
    }
}
