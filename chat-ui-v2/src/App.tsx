import { ChatLayout } from './components/chat/ChatLayout'
import { CommandPalette } from './components/CommandPalette'
import { Toaster } from 'sonner'

function App() {
  return (
    <>
      <ChatLayout />
      <CommandPalette />
      <Toaster
        theme="dark"
        position="bottom-right"
        toastOptions={{
          style: {
            background: 'hsl(var(--background))',
            border: '1px solid hsl(var(--border))',
            color: 'hsl(var(--foreground))',
          },
        }}
        closeButton
        richColors
      />
    </>
  )
}

export default App
