"""CircleCI Pipeline 状态监控（取数统一走 pipeline_api.call_circleci_api）。

本模块只保留：状态格式化、监控循环、CLI 入口。
HTTP 层（header 构造、Session 复用、超时、重试）由 call_circleci_api 统一提供。
"""
import time
import sys

from circleCi.pipeline_api import call_circleci_api, CIRCLECI_API_BASE


def _report_error(silent, message):
    if not silent:
        print(message)


def get_pipeline_status(pipeline_id, silent=False, api_token=None):
    """
    获取pipeline状态

    Args:
        pipeline_id (str): Pipeline ID
        silent (bool): 如果为True，不打印错误信息（用于监控循环中）
        api_token (str): CircleCI API Token（如果不提供则使用配置文件中的）

    Returns:
        dict: Pipeline状态信息，如果失败返回None
    """
    response, error = call_circleci_api(f"pipeline/{pipeline_id}", api_token=api_token)

    if error:
        status_code = error.get('status_code')
        if status_code == 404:
            _report_error(silent, f"❌ Pipeline未找到: {pipeline_id}")
        elif status_code == 401:
            _report_error(silent, "❌ 401错误 - 认证失败，请检查API token")
        elif status_code == 403:
            _report_error(silent, "❌ 403错误 - 权限不足")
        else:
            _report_error(silent, f"❌ 获取pipeline状态失败: {error.get('error')}")
        return None

    return response.json()


def get_pipeline_workflows(pipeline_id, silent=False, api_token=None):
    """
    获取pipeline下的workflows状态

    Args:
        pipeline_id (str): Pipeline ID
        silent (bool): 如果为True，不打印错误信息
        api_token (str): CircleCI API Token（如果不提供则使用配置文件中的）

    Returns:
        list: Workflows列表，如果失败返回None
    """
    response, error = call_circleci_api(
        f"pipeline/{pipeline_id}/workflow", api_token=api_token
    )

    if error:
        status_code = error.get('status_code')
        if status_code == 404:
            _report_error(silent, f"❌ Pipeline workflows未找到: {pipeline_id}")
        elif status_code == 401:
            _report_error(silent, "❌ 401错误 - 认证失败，请检查API token")
        elif status_code == 403:
            _report_error(silent, "❌ 403错误 - 权限不足")
        else:
            _report_error(silent, f"❌ 获取workflows失败: {error.get('error')}")
        return None

    return response.json().get('items', [])


def get_workflow_status(pipeline_id, silent=False, api_token=None):
    """
    获取pipeline的实际构建状态（通过workflows）

    Args:
        pipeline_id (str): Pipeline ID
        silent (bool): 如果为True，不打印错误信息
        api_token (str): CircleCI API Token（如果不提供则使用配置文件中的）

    Returns:
        str: 实际状态（从workflows中获取），如果无法获取则返回None
    """
    workflows = get_pipeline_workflows(pipeline_id, silent=silent, api_token=api_token)

    if not workflows or len(workflows) == 0:
        return None

    # 获取所有workflow的状态
    statuses = [w.get('status', 'unknown') for w in workflows]

    # 如果所有workflow都已完成，返回最后一个状态
    # 如果还有running的，返回running
    if 'running' in statuses:
        return 'running'
    elif 'on_hold' in statuses:
        return 'on_hold'
    elif len(statuses) > 0:
        # 返回最后一个workflow的状态（通常是最新的）
        return statuses[-1]

    return None


def format_status(status):
    """
    格式化状态显示

    Args:
        status (str): 原始状态

    Returns:
        tuple: (显示文本, emoji)
    """
    status_map = {
        'running': ('Running', '🔄'),
        'success': ('Success', '✅'),
        'failing': ('Success', '✅'),  # 当前配置中 Failing 代表成功
        'failed': ('Failed', '❌'),
        'error': ('Error', '❌'),
        'canceled': ('Canceled', '⏹️'),
        'on_hold': ('On Hold', '⏸️'),
        'not_run': ('Not Run', '⚪'),
        'queued': ('Queued', '⏳'),
        'created': ('Created', '📝'),
    }

    status_lower = status.lower() if status else 'unknown'
    display_text, emoji = status_map.get(status_lower, (status, '❓'))
    return display_text, emoji


def monitor_pipeline(pipeline_id, check_interval=5, max_duration=None):
    """
    持续监控pipeline状态

    Args:
        pipeline_id (str): Pipeline ID
        check_interval (int): 检查间隔（秒），默认5秒
        max_duration (int): 最大监控时长（秒），None表示无限制

    Returns:
        str: 最终状态
    """
    print("=" * 60)
    print("📊 开始监控Pipeline状态")
    print("=" * 60)
    print(f"Pipeline ID: {pipeline_id}")
    print(f"检查间隔: {check_interval}秒")
    if max_duration:
        print(f"最大监控时长: {max_duration}秒")
    print("=" * 60)
    print()

    start_time = time.time()
    previous_status = None
    last_status_display_time = start_time  # 初始化为开始时间
    status_display_interval = 30  # 即使状态没变化，也每30秒显示一次进度
    check_count = 0
    # 最终状态：failing 在当前配置中代表成功，所以也作为最终状态
    final_statuses = ['success', 'failing', 'failed', 'error', 'canceled']

    try:
        while True:
            check_count += 1
            current_time = time.time()
            elapsed_time = int(current_time - start_time)

            # 检查是否超过最大时长
            if max_duration and elapsed_time > max_duration:
                print(f"\n⏱️ 已达到最大监控时长 ({max_duration}秒)，停止监控")
                break

            # 获取pipeline基本信息
            pipeline_data = get_pipeline_status(pipeline_id, silent=True)

            if not pipeline_data:
                # 只在第一次失败或每10次检查失败时显示错误信息
                if check_count == 1 or check_count % 10 == 0:
                    print(f"[{time.strftime('%H:%M:%S')}] ⚠️ 无法获取pipeline状态，{check_interval}秒后重试... (第{check_count}次检查)")
                time.sleep(check_interval)
                continue

            pipeline_number = pipeline_data.get('number', 'N/A')
            pipeline_state = pipeline_data.get('state', 'unknown')

            # 优先获取workflow状态（实际构建状态）
            workflow_status = get_workflow_status(pipeline_id, silent=True)

            # 使用workflow状态，如果没有则使用pipeline状态
            if workflow_status:
                current_status = workflow_status
            else:
                current_status = pipeline_state

            # 状态变化时显示，或者每30秒显示一次进度（即使状态没变化）
            should_display = (
                current_status != previous_status or
                (current_time - last_status_display_time) >= status_display_interval
            )

            if should_display:
                display_text, emoji = format_status(current_status)
                print(f"[{time.strftime('%H:%M:%S')}] {emoji} 状态: {display_text} (Pipeline #{pipeline_number})")
                print(f"         已运行时间: {elapsed_time}秒 ({elapsed_time // 60}分{elapsed_time % 60}秒) | 检查次数: {check_count}")

                previous_status = current_status
                last_status_display_time = current_time

            # 如果pipeline已完成，退出循环
            if current_status in final_statuses:
                display_text, emoji = format_status(current_status)
                total_time = int(time.time() - start_time)

                print()
                print("=" * 60)
                print(f"{emoji} Pipeline已完成")
                print("=" * 60)
                print(f"最终状态: {display_text}")
                print(f"Pipeline ID: {pipeline_id}")
                print(f"Pipeline Number: {pipeline_number}")
                print(f"总耗时: {total_time}秒 ({total_time // 60}分{total_time % 60}秒)")
                print(f"总检查次数: {check_count}")
                print("=" * 60)

                return current_status

            # 等待下一次检查
            time.sleep(check_interval)

    except KeyboardInterrupt:
        print("\n\n⚠️ 用户中断监控")
        if previous_status:
            display_text, emoji = format_status(previous_status)
            print(f"当前状态: {emoji} {display_text}")
        return previous_status
    except Exception as e:
        print(f"\n❌ 监控过程中发生错误: {e}")
        return None


def get_pipeline_id_by_number(project_slug, pipeline_number, api_token=None):
    """
    通过pipeline number查找pipeline ID

    Args:
        project_slug (str): 项目slug
        pipeline_number (int): Pipeline编号
        api_token (str): CircleCI API Token（如果不提供则使用配置文件中的）

    Returns:
        str: Pipeline ID，如果未找到返回None
    """
    response, error = call_circleci_api(
        f"project/{project_slug}/pipeline", api_token=api_token
    )

    if error:
        return None

    items = response.json().get('items', [])
    for pipeline in items:
        if pipeline.get('number') == pipeline_number:
            return pipeline.get('id')

    return None


def monitor_by_pipeline_number(project_slug, pipeline_number, check_interval=5, max_duration=None, api_token=None):
    """
    通过pipeline number监控（需要先获取pipeline ID）

    Args:
        project_slug (str): 项目slug
        pipeline_number (int): Pipeline编号
        check_interval (int): 检查间隔（秒）
        max_duration (int): 最大监控时长（秒）
        api_token (str): CircleCI API Token（如果不提供则使用配置文件中的）

    Returns:
        str: 最终状态
    """
    pipeline_id = get_pipeline_id_by_number(project_slug, pipeline_number, api_token=api_token)

    if not pipeline_id:
        print(f"❌ 未找到Pipeline #{pipeline_number}")
        return None

    return monitor_pipeline(pipeline_id, check_interval, max_duration)


def main():
    """
    主函数 - 支持命令行参数
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="CircleCI Pipeline状态监控工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python monitoring.py -i <pipeline-id>                    # 通过Pipeline ID监控
  python monitoring.py -n <pipeline-number> -p <project>   # 通过Pipeline Number监控
  python monitoring.py -i <pipeline-id> -i 5              # 设置检查间隔为5秒
  python monitoring.py -i <pipeline-id> -m 3600           # 设置最大监控时长为1小时
        """
    )

    parser.add_argument(
        '-i', '--pipeline-id',
        type=str,
        help='Pipeline ID（优先使用此参数）'
    )

    parser.add_argument(
        '-n', '--pipeline-number',
        type=int,
        help='Pipeline Number（需要配合--project使用）'
    )

    parser.add_argument(
        '-p', '--project',
        type=str,
        help='项目slug（格式: vcs-type/org-name/repo-name），配合--pipeline-number使用'
    )

    parser.add_argument(
        '--interval',
        type=int,
        default=10,
        help='检查间隔（秒），默认10秒'
    )

    parser.add_argument(
        '-m', '--max-duration',
        type=int,
        help='最大监控时长（秒），默认无限制'
    )

    args = parser.parse_args()

    # 确定使用哪种方式监控
    if args.pipeline_id:
        # 使用Pipeline ID
        monitor_pipeline(args.pipeline_id, args.interval, args.max_duration)
    elif args.pipeline_number and args.project:
        # 使用Pipeline Number和Project
        monitor_by_pipeline_number(args.project, args.pipeline_number, args.interval, args.max_duration)
    else:
        print("❌ 错误: 必须提供以下参数之一:")
        print("  1. --pipeline-id (-i) <pipeline-id>")
        print("  2. --pipeline-number (-n) <number> 和 --project (-p) <project-slug>")
        print("\n使用 --help 查看详细帮助")
        sys.exit(1)


if __name__ == "__main__":
    main()
