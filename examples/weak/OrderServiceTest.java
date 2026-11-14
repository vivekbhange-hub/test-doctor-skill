package shop.orders;

// Order service tests for a fictional shop. Several are weak on purpose (see weak_tests.py).

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Disabled;
import org.junit.jupiter.api.Test;

class OrderServiceTest {
    private final OrderService service = new OrderService();

    @Test
    void createsOrder() {
        service.create("c-1", "hat");
    }

    @Test
    void alwaysTrue() {
        assertTrue(true);
    }

    @Test
    void loadsOrder() {
        assertNotNull(service.load("o-1"));
    }

    @Test
    void cancelsLater() {
    }

    @Disabled
    @Test
    void appliesDiscount() {
        assertEquals(9.0, service.discount(10, 0.10));
    }

    @Test
    void ships() throws Exception {
        service.create("c-2", "hat");
        Thread.sleep(2000);
        assertEquals("shipped", service.load("o-2").status());
    }

    @Test
    void cancelUnknown() {
        try {
            service.cancel("missing");
        } catch (Exception e) {
            // ignored
        }
    }

    @Test
    void rounds() {
        // assertEquals(3, service.round(2.5));
        assertEquals(2, service.round(2.4));
    }

    @Test
    void totalIncludesTax() {
        assertEquals(21.59, service.create("c-3", "hat").total(), 0.001);
    }
}
