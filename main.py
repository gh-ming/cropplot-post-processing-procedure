"""
主入口脚本：把整个后处理管线串联起来

用法示例（Windows cmd）:
    python main.py --in_raster edge_prob.tif --mask cropland_mask.tif --workdir ./out --steps thinning,vectorize,smooth,filter

支持参数：
- --steps: 指定按逗号分隔的阶段, 可选值: thinning, vectorize, smooth, filter
- --dry-run: 仅打印将运行的命令，不实际执行
- --verbose: 更详细的日志

实现说明：优先尝试以模块导入方式调用脚本（如果脚本提供函数或 main），若不可用则使用 subprocess 以独立进程运行脚本文件。
"""

import argparse
import subprocess
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPTS = {
    'thinning': ROOT / 'thinning.py',
    'smooth': ROOT / 'smooth.py',
    'filter': ROOT / 'filter_by_cropland.py',
}


def run_command(cmd, dry_run=False, verbose=False):
    if dry_run or verbose:
        print("[CMD] ", " ".join(cmd))
    if dry_run:
        return 0
    proc = subprocess.run(cmd, shell=False)
    return proc.returncode


def call_script(script_path: Path, args: list, dry_run=False, verbose=False):
    # 尝试以 python -m 脚本方式调用，保持与脚本自身运行时行为一致
    cmd = [sys.executable, str(script_path)] + args
    return run_command(cmd, dry_run=dry_run, verbose=verbose)


def parse_steps(s: str):
    return [p.strip() for p in s.split(',') if p.strip()]


def main():
    p = argparse.ArgumentParser(description='Cropplot post-processing pipeline entry')
    p.add_argument('--in_raster', help='输入边缘概率图（GeoTIFF）', default='edge_map/GF_NM_T48TXL_E67970_N450984.tif')
    p.add_argument('--out_dir', help='输出目录', default='out_dir')
    p.add_argument('--mask', help='耕地掩膜（Mask TIF），filter 阶段需要', default='cropland/GF_NM_T48TXL_E67970_N450984.tif')
    p.add_argument('--steps', help='要运行的阶段，逗号分隔: thinning,smooth,filter', default='thinning,smooth,filter')
    p.add_argument('--dry-run', action='store_true', help='只打印命令不执行')
    p.add_argument('--verbose', action='store_true', help='打印详细信息')

    # 额外通用参数，可传递给每个脚本（简单起见，作为未解析的字符串传下去）
    p.add_argument('--extra', help='额外参数，传递给每个脚本（示例: "--opt 1 --flag"）', default='')

    args = p.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    steps = parse_steps(args.steps)

    thinning_out = out_dir / 'parcels.shp'
    smooth_out = out_dir / 'parcels_smooth.shp'
    filter_out = out_dir / 'parcels_filtered.shp'

    for step in steps:
        step = step.lower()
        if step == 'thinning':
            script = SCRIPTS['thinning']
            # thinning.py 在此仓库中负责从边缘概率图完成栅格精炼并（已实现）矢量化为 parcels.shp
            cmd_args = ['--in_raster', args.in_raster, '--out_shp', str(thinning_out)]
            if args.extra:
                cmd_args += args.extra.split()
            print('\n=== Running thinning ===')
            rc = call_script(script, cmd_args, dry_run=args.dry_run, verbose=args.verbose)
            if rc != 0:
                print('thinning failed with code', rc)
                sys.exit(rc)
        elif step == 'smooth':
            script = SCRIPTS['smooth']
            # smooth.py 期望输入为一个 Shapefile（由 thinning 输出）
            cmd_args = ['--input_shp', str(thinning_out), '--output_shp', str(smooth_out)]
            if args.extra:
                cmd_args += args.extra.split()
            print('\n=== Running smooth ===')
            rc = call_script(script, cmd_args, dry_run=args.dry_run, verbose=args.verbose)
            if rc != 0:
                print('smooth failed with code', rc)
                sys.exit(rc)

        elif step == 'filter':
            if not args.mask:
                print('filter step needs --mask argument')
                sys.exit(2)
            script = SCRIPTS['filter']
            cmd_args = ['--parcel_shp', str(smooth_out), '--mask_tif', args.mask, '--output_shp', str(filter_out)]
            if args.extra:
                cmd_args += args.extra.split()
            print('\n=== Running filter ===')
            rc = call_script(script, cmd_args, dry_run=args.dry_run, verbose=args.verbose)
            if rc != 0:
                print('filter failed with code', rc)
                sys.exit(rc)


        else:
            print('Unknown step:', step)
            sys.exit(3)

    print('\nPipeline finished successfully. Outputs:')
    print(' Thinning (parcels) output:', thinning_out)
    print(' Smooth output:', smooth_out)
    print(' Filtered output:', filter_out)


if __name__ == '__main__':
    main()
