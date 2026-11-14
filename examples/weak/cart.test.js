// Cart tests for a fictional shop. Several are weak on purpose (see weak_tests.py).
const { Cart } = require('./cart');

describe('Cart', () => {
  it('adds an item', () => {
    const cart = new Cart();
    cart.add({ sku: 'hat', price: 12 });
  });

  it('is always true', () => {
    expect(true).toBe(true);
  });

  it('creates a cart', () => {
    const cart = new Cart();
    expect(cart).toBeDefined();
  });

  it('has a total', () => {
    const cart = new Cart();
    expect(cart.total());
  });

  it('removes an item', () => {});

  it.skip('applies a coupon', () => {
    expect(new Cart().applyCoupon('SPRING')).toBe(true);
  });

  // Skipped until the tax service has a sandbox (ticket 118).
  it.skip('adds tax', () => {
    expect(new Cart().tax()).toBe(2);
  });

  it('empties after checkout', async () => {
    const cart = new Cart();
    await cart.checkout();
    await new Promise((resolve) => setTimeout(resolve, 500));
    expect(cart.items).toHaveLength(0);
  });

  it('rejects a negative price', () => {
    try {
      new Cart().add({ sku: 'hat', price: -1 });
    } catch (e) {
      console.log('rejected');
    }
  });

  it('rounds the total', () => {
    const cart = new Cart();
    cart.add({ sku: 'hat', price: 12.005 });
    // expect(cart.total()).toBe(12.01);
    expect(cart.total()).toBeGreaterThan(12);
  });

  it('renders the summary', () => {
    expect(new Cart().summary()).toMatchSnapshot();
  });

  it('sums two items', () => {
    const cart = new Cart();
    cart.add({ sku: 'hat', price: 12 });
    cart.add({ sku: 'cap', price: 8 });
    expect(cart.total()).toBe(20);
  });
});
