export function FrequencyModal({ onClose }: { onClose: () => void }) {
  return (
    <div className="modal-mask show">
      <div className="modal">
        <h3>💡 高频词补充策略</h3>
        <p>系统会从完整语言表中提取高频、易混淆和需要统一维护的中文术语，生成候选批次、项目说明和翻译提示词。</p>
        <ul className="strategy-list">
          <li>筛选：先按中文提取候选，再按项目术语库中文去重。</li>
          <li>跳过：项目术语表已存在的中文不会进入候选，也不会跨语言自动补译。</li>
          <li>审核：新增候选必须在表格里确认当前语言译文 / 备选译文 / 分类 / 备注后，点加入才会进入项目术语库。</li>
          <li>审计：每次扫描会在 run 日志里记录候选数、去重数、新增数和跳过数。</li>
        </ul>
        <div className="modal-foot"><button className="btn btn-primary" onClick={onClose}>知道了</button></div>
      </div>
    </div>
  )
}
