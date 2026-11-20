import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Modal, ModalBody } from '../src/components/ui/Modal'
import '../src/styles/global.css'

function ModalFixture() {
  const [parent, setParent] = useState(false)
  const [child, setChild] = useState(false)
  const empty = new URLSearchParams(location.search).has('empty-modal')
  return <>
    <button onClick={() => setParent(true)}>Open parent</button>
    <Modal isOpen={parent} title="Parent dialog" onClose={() => setParent(false)} showCloseButton={!empty}>
      <ModalBody>
        <p>Parent content</p>
        {!empty && <button onClick={() => setChild(true)}>Open child</button>}
      </ModalBody>
    </Modal>
    <Modal isOpen={child} title="Child dialog" onClose={() => setChild(false)}>
      <ModalBody><button>Child action</button></ModalBody>
    </Modal>
  </>
}

createRoot(document.getElementById('root')!).render(<ModalFixture />)
