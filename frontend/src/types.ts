// frontend/src/types.ts
import * as THREE from 'three'

export interface MeasurePoint {
  id: string
  pos: THREE.Vector3
  label: string
}

export type Phase = 'upload' | 'viewing'

export const MORPH_TARGETS = [
  'nose_bridge_height',
  'nose_tip_projection',
  'nose_wing_width',
  'eye_corner_outer',
  'eye_height',
  'double_eyelid',
  'jaw_width',
  'chin_length',
  'chin_projection',
  'cheekbone_width',
  'temple_width',
  'lip_fullness',
] as const

export type MorphTargetName = typeof MORPH_TARGETS[number]

export const MORPH_LABELS: Record<MorphTargetName, string> = {
  nose_bridge_height:  '山根高度',
  nose_tip_projection: '鼻尖投影',
  nose_wing_width:     '鼻翼宽度',
  eye_corner_outer:    '外眼角',
  eye_height:          '眼裂高度',
  double_eyelid:       '双眼皮',
  jaw_width:           '下颌角宽度',
  chin_length:         '下巴长度',
  chin_projection:     '下巴前突',
  cheekbone_width:     '颧骨宽度',
  temple_width:        '太阳穴宽度',
  lip_fullness:        '嘴唇丰满度',
}

export const MORPH_GROUPS: Record<string, MorphTargetName[]> = {
  'Nose 鼻部':         ['nose_bridge_height', 'nose_tip_projection', 'nose_wing_width'],
  'Eyes 眼部':         ['eye_corner_outer', 'eye_height', 'double_eyelid'],
  'Jaw & Chin 下颌':   ['jaw_width', 'chin_length', 'chin_projection'],
  'Contour 轮廓':      ['cheekbone_width', 'temple_width', 'lip_fullness'],
}
