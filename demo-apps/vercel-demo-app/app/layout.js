export const metadata = {
  title: 'Order Service',
  description: 'E-commerce order fulfillment API',
}

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
