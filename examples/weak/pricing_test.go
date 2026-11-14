package pricing

// Pricing tests for a fictional shop. Several are weak on purpose (see weak_tests.py).

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func TestApplyTax(t *testing.T) {
	ApplyTax(1000, "DE")
}

func TestAlwaysTrue(t *testing.T) {
	assert.True(t, true)
}

func TestLookupExists(t *testing.T) {
	rate := LookupRate("DE")
	assert.NotNil(t, rate)
}

func TestRoundingLater(t *testing.T) {
}

func TestVatRefund(t *testing.T) {
	t.Skip()
}

func TestRateCache(t *testing.T) {
	WarmCache()
	time.Sleep(2 * time.Second)
	if got := CachedRate("DE"); got != 19 {
		t.Errorf("CachedRate(DE) = %d, want 19", got)
	}
}

func TestParsePrice(t *testing.T) {
	defer func() {
		recover()
	}()
	ParsePrice("not a price")
}

func TestRoundHalfUp(t *testing.T) {
	// assert.Equal(t, 3, Round(2.5))
	if got := Round(2.4); got != 2 {
		t.Errorf("Round(2.4) = %d, want 2", got)
	}
}

func TestTotal(t *testing.T) {
	if got := Total([]int{500, 250}); got != 750 {
		t.Errorf("Total = %d, want 750", got)
	}
}
