export default function Home() {
  return (
    <main style={{ padding: '2rem', fontFamily: 'sans-serif' }}>
      <h1>Order Service API</h1>
      <p>Endpoints:</p>
      <ul>
        <li><code>GET /api/orders</code> - List recent orders</li>
        <li><code>GET /api/orders?status=pending</code> - Filter by status</li>
      </ul>
    </main>
  )
}
