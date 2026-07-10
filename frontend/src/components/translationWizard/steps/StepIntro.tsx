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
      <div className="panel-title"><span className="badge">STEP 1</span>确认项目资料与参考素材</div>
      <div className="panel-desc">已从项目描述带入基础信息；这里只需要补充本次任务特有的风格、玩法、角色或素材。</div>
      <textarea value={intro} onChange={(event) => setIntro(event.target.value)} placeholder={'游戏名：《星际边境》\n类型：科幻 SLG\n目标用户：欧美移动端玩家\n玩法：基地建造 + 英雄养成 + 联盟战争'} />
      <div className="field-foot">
        <span>{intro.trim().length} 字</span>
        <span className={intro.trim().length > 20 || project.description ? 'ok' : 'warn'}>{intro.trim().length > 20 || project.description ? <><CheckCircle2 size={13} aria-hidden="true" />信息可用于生成提示词</> : <><AlertTriangle size={13} aria-hidden="true" />建议补充更多信息</>}</span>
      </div>
      <div className="upload-row">
        <FileBox label="上传 Markdown / 文档 / 图片 / PDF / 音视频素材" onFile={onUploadAsset} />
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
