import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import { ArtifactNote, FileBox } from '../../shared/WorkflowPrimitives'
import type { Artifact, Project } from '../../../types'

export function StepIntro({
  project,
  intro,
  setIntro,
  assetArtifacts,
  onUploadAsset
}: {
  project: Project
  intro: string
  setIntro: (value: string) => void
  assetArtifacts: Artifact[]
  onUploadAsset: (file: File) => void
}) {
  return (
    <>
      <div className="panel-title"><span className="badge">步骤 1/9</span>项目资料</div>
      <div className="panel-desc">补充本次翻译依据。</div>
      <textarea value={intro} onChange={(event) => setIntro(event.target.value)} placeholder="本次内容、语气、角色或玩法要求" />
      <div className="field-foot">
        <span>{intro.trim().length} 字</span>
        <span className={intro.trim().length > 20 || project.description ? 'ok' : 'warn'}>{intro.trim().length > 20 || project.description ? <><CheckCircle2 size={13} aria-hidden="true" />可用于分析</> : <><AlertTriangle size={13} aria-hidden="true" />建议补充</>}</span>
      </div>
      <div className="upload-row">
        <FileBox label="上传参考资料" onFile={onUploadAsset} />
        {assetArtifacts.length ? (
          <div className="asset-list">
            <div className="ai-header">已归档参考素材</div>
            {assetArtifacts.map((artifact) => <ArtifactNote key={artifact.id} artifact={artifact} compact />)}
          </div>
        ) : null}
      </div>
    </>
  )
}
